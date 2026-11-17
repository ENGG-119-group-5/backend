"""Thesis matcher: one Claude call scores every invention in the graph against an
investment-thesis PDF (MVP, "Pre Commercial Tech" deck slide 5).

    thesis PDF + merged TTO/USPTO record of each invention
        -> Claude (structured output): label + 4 fit scores, each with a quote
           (a second call covers any invention Claude skipped)
        -> verify_quotes(): a quote counts only if it really appears in that record
        -> rank(): strong > potential > none, then by total fit score

The LLM never supplies facts: it only judges the records we give it, and every
score must quote the record it is based on.

In plain words: this is the AI part. An investor's thesis says what they want to fund
(for example "immune therapies, early stage, ready to license"). We hand Claude that
PDF plus a written summary of every Dartmouth invention, and ask it to grade each
invention on four questions (area, problem, stage, deal), from 0 to 2, and to copy a
short quote from the invention's record as proof for each grade. Our own code then
checks every quote really appears in the record, so made-up evidence is caught and
flagged on screen. Finally, the inventions are sorted: strong matches first.
"""
import base64
import re
from typing import Literal

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"
FITS = {   # key -> question the model answers (also shown in the UI)
    "area": "Area fit: is it in the sectors or therapeutic areas the thesis targets?",
    "problem": "Problem fit: does it address a need or gap the thesis names?",
    "stage": "Stage fit: is it mature enough for this investor's stage?",
    "deal": "Deal fit: do its IP status and what the lab is looking for allow the deal the thesis wants?",
}
LABEL_ORDER = {"strong": 0, "potential": 1, "none": 2}

SYSTEM = f"""You are a venture analyst screening university inventions against an investment thesis.
The thesis is the attached PDF. The inventions are listed after it, each starting with "### <id>".

For EVERY invention, exactly once:
- Score four fits from 0 to 2 (0 = no, 1 = partly, 2 = clearly yes):
{chr(10).join(f"  - {k}: {q}" for k, q in FITS.items())}
- For each fit, give a one-sentence reason and copy one short quote (a phrase or sentence,
  word for word) from THAT invention's record as evidence. Never quote the thesis and never
  paraphrase inside a quote. If the record holds no evidence for a fit, leave the quote empty.
- Label it "strong" (clear area and problem fit, nothing that rules it out), "potential"
  (relevant, but stage, deal or problem fit is a concern) or "none" (outside the thesis).
- Write a one-sentence summary of why it ranks where it does.

Also summarize in 2-3 sentences what the thesis looks for (sectors, problems, stage, deal type).
Judge only from the thesis and the records. Do not add outside facts about the inventions."""


# ------------------------------------------------------------ Claude output schema
class FitCheck(BaseModel):
    score: int    # 0 no, 1 partly, 2 clearly
    reason: str
    quote: str    # verbatim from the invention record, or ""


class Verdict(BaseModel):
    invention_id: str
    label: Literal["strong", "potential", "none"]
    area: FitCheck
    problem: FitCheck
    stage: FitCheck
    deal: FitCheck
    summary: str


class MatchOutput(BaseModel):
    thesis_summary: str
    verdicts: list[Verdict]


class MatchError(Exception):
    """Claude call finished but gave no usable answer. `status` is the HTTP status to return."""
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ inventions
INVENTIONS_CYPHER = """
MATCH (t:Technology)
OPTIONAL MATCH (t)-[:CLAIMS_IP]->(r:IpRef)
WITH t, collect(r{.raw_label, .ip_type}) AS refs
OPTIONAL MATCH (t)-[:PROTECTED_BY]->(p:Patent)
OPTIONAL MATCH (p)-[:ASSIGNED_TO]->(a:Assignee)
WITH t, refs, p, collect(a.name) AS owners
WITH t, refs, collect(p{.patent_key, .doc_type, .title, .abstract, .grant_date, .filing_date,
                       .government_interest, assignees: owners}) AS patents
OPTIONAL MATCH (i:Inventor)-[l:LISTED_ON]->(t)
RETURN t{.tto_id, .title, .category, .status, .rights, .description, .advantages, .features,
         .looking_for} AS t,
       refs, patents,
       collect(i.name + coalesce(' (' + l.title_affiliation + ')', '')) AS people
ORDER BY t.tto_id
"""


async def load_inventions(tx) -> list[dict]:
    """Every Technology with its TTO IP claims, confirmed USPTO patents and people."""
    result = await tx.run(INVENTIONS_CYPHER)
    return [{**r["t"], "refs": r["refs"], "patents": r["patents"], "people": r["people"]}
            async for r in result]


def invention_text(inv: dict) -> str:
    """The merged TTO + USPTO record Claude reads, and that quotes are checked against."""
    lines = [f"### {inv['tto_id']}: {inv['title']}",
             f"Category: {inv.get('category') or 'unknown'}. TTO status: {(inv.get('status') or 'unknown').replace('_', ' ')}."
             + (f" Rights available: {inv['rights'].replace('_', ' ')}." if inv.get("rights") else "")]
    if inv.get("description"):
        lines.append(f"Description: {inv['description']}")
    if inv.get("advantages"):
        lines.append("Advantages: " + " ".join(inv["advantages"]))
    if inv.get("features"):
        lines.append("Details: " + " ".join(inv["features"]))
    if inv.get("looking_for"):
        lines.append("Looking for: " + " ".join(inv["looking_for"]))
    refs = [f"{r['raw_label']} ({(r.get('ip_type') or 'unknown').replace('_', ' ')})" for r in inv.get("refs", [])]
    lines.append("IP listed by the TTO: " + ("; ".join(refs) if refs else "none listed"))
    for p in inv.get("patents", []):
        when = f"granted {p['grant_date']}" if p.get("grant_date") else f"filed {p.get('filing_date') or 'unknown'}"
        kind = "granted patent" if p.get("doc_type") == "grant" else "published application"
        funding = " Federally funded." if (p.get("government_interest") or "").strip() else ""
        owners = f" Assignees: {'; '.join(p['assignees'])}." if p.get("assignees") else ""
        lines.append(f"USPTO record {p['patent_key']} ({kind}, {when}): {p.get('title') or ''}. "
                     f"{p.get('abstract') or ''}{funding}{owners}")
    if not inv.get("patents"):
        lines.append("USPTO records: no confirmed patent or application.")
    if inv.get("people"):
        lines.append("People: " + "; ".join(inv["people"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- Claude call
async def run_match(client: anthropic.AsyncAnthropic, pdf: bytes, inventions: list[dict]) -> MatchOutput:
    """Thesis PDF + all invention records -> MatchOutput, in one Claude call. In a long list
    Claude occasionally skips an invention; those few get one more call of their own."""
    output = await score(client, pdf, inventions)
    done = {v.invention_id for v in output.verdicts}
    missing = [inv for inv in inventions if inv["tto_id"] not in done]
    if missing:
        extra = await score(client, pdf, missing)
        wanted = {inv["tto_id"] for inv in missing}
        output.verdicts += [v for v in extra.verdicts if v.invention_id in wanted]
    return output


async def score(client: anthropic.AsyncAnthropic, pdf: bytes, inventions: list[dict]) -> MatchOutput:
    """One Claude call over the given inventions."""
    records = "\n\n".join(invention_text(inv) for inv in inventions)
    async with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        # Server-side fallback: if the model declines, the API retries on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_format=MatchOutput,
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.standard_b64encode(pdf).decode()}},
            {"type": "text", "text": f"Inventions ({len(inventions)}):\n\n{records}"},
        ]}],
    ) as stream:
        message = await stream.get_final_message()

    if message.stop_reason == "refusal":
        raise MatchError("Claude declined to assess this document.", status=422)
    if message.stop_reason == "max_tokens":
        raise MatchError("Claude's answer was cut off before it finished.")
    if message.parsed_output is None:
        raise MatchError("Claude did not return a valid match result.")
    return message.parsed_output


# -------------------------------------------------- checks outside the model
def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip(" .\"'…")


def quote_found(quote: str, record_text: str) -> bool:
    """True only if the quote (8+ characters) appears word for word in the record."""
    q = _norm(quote)
    return len(q) >= 8 and q in _norm(record_text)


def rank(matches: list[dict]) -> list[dict]:
    """Strong first, then potential, then none; within a label, higher total fit first,
    then the stronger rule-based IP score (e.g. a granted patent before an application)."""
    return sorted(matches, key=lambda m: (LABEL_ORDER[m["label"]], -m["totalScore"],
                                          -(m["technology"].get("ipScore") or 0), m["technology"]["title"]))
