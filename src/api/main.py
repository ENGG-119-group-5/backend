"""FastAPI app: /search and /technology/{id} over the Neo4j graph (data_contract v0.3).

Run from the repo root:  uvicorn api.main:app --app-dir src --reload
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from neo4j import AsyncGraphDatabase

from .models import (AuditEntry, EntityRef, InventorSummary, IpScore, LinkEvidence,
                     PatentWithLink, SimilarTechnology, SourceRef, TechnologyDetail)
from .scoring import compute_ip_score

import config
NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD = config.NEO4J_URI, config.NEO4J_USER, config.NEO4J_PASSWORD
NEO4J_DATABASE = config.NEO4J_DATABASE
TTO_URL = os.getenv("TTO_LISTING_URL", "https://tto.dartmouth.edu/engage-us/licensing-opportunities")

LABELS = {"technology": "Technology", "patent": "Patent", "inventor": "Inventor"}
ID_KEY = {"technology": "tto_id", "patent": "patent_key", "inventor": "inventor_id"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    await driver.verify_connectivity()
    app.state.driver = driver
    yield
    await driver.close()


app = FastAPI(title="VC Due Diligence API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ helpers
async def read(request: Request, work):
    async with request.app.state.driver.session(database=NEO4J_DATABASE) as s:
        return await s.execute_read(work)


async def rows(tx, cypher: str, **params) -> list[dict]:
    result = await tx.run(cypher, **params)
    return [r.data() async for r in result]


def iso(v) -> str | None:
    if v is None:
        return None
    return v.iso_format() if hasattr(v, "iso_format") else str(v)


def map_status(s):
    return "available" if s in ("available_for_license", "portfolio_available_for_review") else "unknown"


def link_method(methods) -> str:
    """data_contract match_method list -> API contract LinkEvidence.method."""
    m = methods or []
    if "human_review" in m:
        return "analyst"
    if "title_inventor" in m:
        return "title_inventor"
    return "patent_number"   # patent / application / publication number = identifier match


def number_label(p: dict) -> str:
    pn, an = p.get("patent_number"), p.get("application_number")
    if p.get("doc_type") == "grant" and pn:
        return f"US {int(pn):,}" if str(pn).isdigit() else f"US {pn}"
    if an:
        return f"US App. {an[:2]}/{int(an[2:]):,}" if str(an).isdigit() and len(an) > 2 else f"US App. {an}"
    return p.get("publication_number") or p.get("patent_key") or ""


def is_synthetic(record: dict) -> bool:
    """Synthetic demo data (data/demo/) must never link to real USPTO / Google Patents pages."""
    return "synthetic" in (record.get("quality_flags") or [])


def patent_url(p: dict) -> str | None:
    if is_synthetic(p):
        return None
    if p.get("doc_type") == "grant" and p.get("patent_number"):
        return f"https://patents.google.com/patent/US{p['patent_number']}"
    if p.get("publication_number"):
        return f"https://patents.google.com/patent/{p['publication_number']}"
    return None


SCORE_INPUTS = """
MATCH (t:Technology) WHERE $ids IS NULL OR t.tto_id IN $ids
OPTIONAL MATCH (t)-[l:PROTECTED_BY]->(p:Patent)
RETURN t.tto_id AS id, t.status AS status,
  t.override_score AS oScore, t.override_reason AS oReason,
  t.override_analyst AS oAnalyst, t.override_at AS oAt,
  collect(CASE WHEN p IS NULL THEN NULL ELSE {
    patent_key: p.patent_key, doc_type: p.doc_type, patent_number: p.patent_number,
    application_number: p.application_number, publication_number: p.publication_number,
    grant_date: p.grant_date, filing_date: p.filing_date,
    has_funding: coalesce(trim(p.government_interest), '') <> '',
    quality_flags: p.quality_flags, confidence: l.confidence } END) AS patents
"""


def score_from_row(r: dict) -> dict:
    patents = [{**p, "grant_date": iso(p.get("grant_date")), "filing_date": iso(p.get("filing_date")),
                "number_label": number_label(p), "url": patent_url(p)} for p in r["patents"]]
    override = None
    if r["oScore"] is not None:
        override = {"score": r["oScore"], "reason": r["oReason"],
                    "analyst": r["oAnalyst"], "at": iso(r["oAt"])}
    return compute_ip_score(map_status(r["status"]), patents, override)


def clip(text: str | None, n: int = 160) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ------------------------------------------------------------------- search
@app.get("/search")
async def search(
    request: Request,
    q: str = Query("", description="Search text. Empty returns everything of the type."),
    type: str = Query("all", pattern="^(all|technology|patent|inventor)$"),
    limit: int = Query(25, ge=1, le=100),
):
    q = q.strip()
    props = "{.tto_id, .patent_key, .inventor_id, .title, .name, .description, .abstract, .source}"

    async def work(tx):
        if q:
            tokens = [t.lower() for t in q.split()]
            fields = ("[n.title, n.name, n.description, n.abstract, n.tto_id, "
                      "n.patent_number, n.application_number, n.publication_number]")
            hits = []
            for kind, label in LABELS.items():
                if type in ("all", kind):
                    found = await rows(
                        tx,
                        f"""MATCH (n:{label})
                            WHERE all(tok IN $tokens WHERE any(v IN {fields}
                                  WHERE v IS NOT NULL AND toLower(toString(v)) CONTAINS tok))
                            RETURN n{props} AS n""",
                        tokens=tokens,
                    )
                    for r in found:
                        n = r["n"]
                        head = (n.get("title") or n.get("name") or "").lower()
                        hits.append({"kind": kind, "n": n,
                                     "relevance": 1.0 if all(t in head for t in tokens) else 0.5})
        else:
            hits = []
            for kind, label in LABELS.items():
                if type in ("all", kind):
                    for r in await rows(tx, f"MATCH (n:{label}) RETURN n{props} AS n"):
                        hits.append({"kind": kind, "n": r["n"], "relevance": 1.0})

        tech_ids = [h["n"]["tto_id"] for h in hits if h["kind"] == "technology"]
        scores = {}
        if tech_ids:
            for r in await rows(tx, SCORE_INPUTS, ids=tech_ids):
                scores[r["id"]] = score_from_row(r)["effective"]
        return hits, scores

    hits, scores = await read(request, work)

    out = []
    for h in hits:
        kind, n = h["kind"], h["n"]
        id_ = n[ID_KEY[kind]]
        snippet = {"technology": n.get("description"), "patent": n.get("abstract"),
                   "inventor": f"Inventor ({n.get('source')})" if n.get("source") else "Inventor"}[kind]
        hit = {"type": kind, "id": id_, "title": n.get("title") or n.get("name") or id_,
               "snippet": clip(snippet), "relevance": h["relevance"]}
        if kind == "technology":
            hit["ipScore"] = scores.get(id_, 0.0)
        out.append(hit)

    order = {"technology": 0, "patent": 1, "inventor": 2}
    if q:   # best match first, shortlist score breaks ties
        out.sort(key=lambda h: (-h["relevance"], -h.get("ipScore", 0)))
    else:   # shortlist: technologies by ipScore desc, then the rest alphabetically
        out.sort(key=lambda h: (order[h["type"]], -h.get("ipScore", 0), h["title"].lower()))
    return {"query": q, "type": type, "total": len(out), "hits": out[:limit]}


# ---------------------------------------------------------- technology/{id}
@app.get("/technology/{id}", response_model=TechnologyDetail)
async def get_technology(request: Request, id: str):
    async def work(tx):
        tech = await rows(tx, """MATCH (t:Technology {tto_id: $id})
            RETURN t{.tto_id, .title, .category, .status, .description, .quality_flags,
                     .source_document, .source_page} AS t""", id=id)
        if not tech:
            return None
        return {
            "t": tech[0]["t"],
            # confirmed links only; POSSIBLY_PROTECTED_BY belongs to the review queue
            "patents": await rows(tx, """MATCH (:Technology {tto_id: $id})-[l:PROTECTED_BY]->(p:Patent)
                RETURN p{.patent_key, .doc_type, .patent_number, .application_number,
                         .publication_number, .title, .grant_date} AS p,
                       l.match_method AS methods, l.confidence AS confidence
                ORDER BY l.confidence DESC, p.patent_key""", id=id),
            "tto_people": await rows(tx, """MATCH (i:Inventor)-[r:LISTED_ON]->(:Technology {tto_id: $id})
                RETURN i{.inventor_id, .name, .name_key} AS i, r.title_affiliation AS aff
                ORDER BY i.name""", id=id),
            "uspto_people": await rows(tx, """MATCH (:Technology {tto_id: $id})-[:PROTECTED_BY]->(:Patent)
                <-[:INVENTED]-(i:Inventor)
                RETURN DISTINCT i{.inventor_id, .name, .name_key} AS i ORDER BY i.name""", id=id),
            # Not in data_contract v0.3 yet; empty until someone writes these nodes.
            "audit": await rows(tx, """MATCH (a:AuditEntry)-[:ABOUT]->(:Technology {tto_id: $id})
                RETURN properties(a) AS a ORDER BY a.at DESC""", id=id),
            "score": await rows(tx, SCORE_INPUTS, ids=[id]),
        }

    d = await read(request, work)
    if d is None:
        raise HTTPException(status_code=404, detail=f"Technology '{id}' not found")

    t = d["t"]
    tech_ref = EntityRef(type="technology", id=t["tto_id"], label=t["title"])

    # People are not merged across sources yet (SAME_AS is v2): show TTO people with
    # their affiliation, then add USPTO inventors whose name_key is not already shown.
    people, seen = [], set()
    for r in d["tto_people"]:
        people.append(InventorSummary(id=r["i"]["inventor_id"], name=r["i"]["name"], affiliation=r["aff"]))
        seen.add(r["i"]["name_key"])
    for r in d["uspto_people"]:
        if r["i"]["name_key"] not in seen:
            people.append(InventorSummary(id=r["i"]["inventor_id"], name=r["i"]["name"], affiliation=None))
            seen.add(r["i"]["name_key"])

    doc, page = t.get("source_document"), t.get("source_page")
    synthetic = is_synthetic(t)
    return TechnologyDetail(
        id=t["tto_id"], title=t["title"], tto_case_number=t["tto_id"],
        status=map_status(t.get("status")), summary=t.get("description") or "",
        categories=[t["category"]] if t.get("category") else [],
        published_at=None,
        sources=[] if synthetic else [SourceRef(kind="tto", url=TTO_URL,
                           label=f"TTO listing {t['tto_id']}" + (f" ({doc}, p. {page})" if doc else ""))],
        synthetic=synthetic,
        patents=[PatentWithLink(
            id=r["p"]["patent_key"], number=number_label(r["p"]), title=r["p"]["title"],
            granted_at=iso(r["p"].get("grant_date")),
            link=LinkEvidence(method=link_method(r["methods"]), confidence=r["confidence"] or 0.0),
        ) for r in d["patents"]],
        inventors=people,
        ip_score=IpScore.model_validate(score_from_row(d["score"][0])),
        similar=[],   # no similarity data in the graph yet
        audit_log=[AuditEntry(
            id=str(a["id"]), at=iso(a["at"]), analyst=a["analyst"], action=a["action"],
            entity=tech_ref, from_=a.get("from"), to=str(a["to"]), reason=a.get("reason") or "",
        ) for a in (r["a"] for r in d["audit"])],
    )
