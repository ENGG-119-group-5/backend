"""Pydantic models mirroring src/lib/api/types.ts (camelCase on the wire).

In plain words: these classes describe the exact shape of every answer the API sends
(which fields, and what kind of value each one holds). The web app has a matching
list in its src/lib/api/types.ts. If an answer does not fit the shape, the API stops
with an error instead of sending the website something it cannot read.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SourceRef(CamelModel):
    kind: Literal["tto", "uspto", "derived"]
    label: str
    url: str


class EntityRef(CamelModel):
    type: Literal["technology", "patent", "inventor"]
    id: str
    label: str


class LinkEvidence(CamelModel):
    method: Literal["patent_number", "title_inventor", "analyst"]
    confidence: float


class PatentSummary(CamelModel):
    id: str
    number: str
    granted_at: str | None
    title: str | None = None


class PatentWithLink(PatentSummary):
    link: LinkEvidence


class InventorSummary(CamelModel):
    id: str
    name: str
    affiliation: str | None


class SimilarTechnology(EntityRef):
    similarity: float


class IpIndicator(CamelModel):
    key: str
    label: str
    value: str
    normalized: float
    weight: float
    contribution: float
    source: SourceRef | None = None


class ScoreOverride(CamelModel):
    score: float
    reason: str
    analyst: str
    at: str


class IpScore(CamelModel):
    rubric: str
    computed: float
    indicators: list[IpIndicator]
    override: ScoreOverride | None
    effective: float


class AuditEntry(CamelModel):
    model_config = ConfigDict(
        alias_generator=lambda f: "from" if f == "from_" else to_camel(f),
        populate_by_name=True,
    )
    id: str
    at: str
    analyst: str
    action: Literal["score_override", "match_decision"]
    entity: EntityRef
    from_: str | None
    to: str
    reason: str


class TechnologyDetail(CamelModel):
    id: str
    title: str
    tto_case_number: str
    status: Literal["available", "licensed", "unknown"]
    summary: str
    categories: list[str]
    published_at: str | None
    sources: list[SourceRef]
    patents: list[PatentWithLink]
    inventors: list[InventorSummary]
    ip_score: IpScore
    similar: list[SimilarTechnology]
    audit_log: list[AuditEntry]
    synthetic: bool = False   # demo data from data/demo/: made up, no real source links


# --------------------------------------------------------- thesis matching (/match)
class TechnologySummary(CamelModel):
    id: str
    title: str
    tto_case_number: str
    status: Literal["available", "licensed", "unknown"]
    ip_score: float | None = None


class FitScore(CamelModel):
    key: Literal["area", "problem", "stage", "deal"]
    question: str
    score: int                # 0 no, 1 partly, 2 clearly
    reason: str
    quote: str                # evidence copied from the invention record
    quote_verified: bool      # True only if the quote really appears in the record


class TechnologyMatch(CamelModel):
    technology: TechnologySummary
    category: str | None
    label: Literal["strong", "potential", "none"]
    total_score: int          # sum of the four fit scores, 0-8
    summary: str
    fits: list[FitScore]


class MatchResponse(CamelModel):
    thesis_name: str
    thesis_sha256: str
    thesis_summary: str
    model: str
    source: Literal["saved_demo", "live"]
    generated_at: str
    matches: list[TechnologyMatch]
    unassessed_ids: list[str]  # inventions Claude skipped (never filled in by us)


class SampleThesis(CamelModel):
    name: str
    title: str
