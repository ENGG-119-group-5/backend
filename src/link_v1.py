"""
Linking v1: TTO technologies -> USPTO patents, by exact identifiers only.

Rules (in order of trust):
  1. granted patent number   -> confidence 1.0
  2. application number      -> confidence 1.0
  3. publication number      -> confidence 0.9, BUT if the patent's application or
     patent number disagrees with the TTO page, the link is 'uncertain'
     (the TTO page has a copy-paste error somewhere) -> human review.

Only 'confirmed' links become PROTECTED_BY in the graph. 'uncertain' links become
POSSIBLY_PROTECTED_BY, so that graph queries never present them as facts.

In plain words: we now have two piles of records, inventions (from the TTO) and
patents (from USPTO). This script decides which patent belongs to which invention,
using only exact numbers printed on the TTO page, never guesses based on similar
titles. A match the numbers fully agree on is "confirmed" and treated as fact. A match
where the numbers disagree is "uncertain" and kept aside for a person to review.
This is step 3 of the data pipeline.

Usage:
    python link_v1.py technologies_life_sciences.json test_fixtures/uspto_patents_test.json -o links.json
    python link_v1.py ... --neo4j          # also write the links to Neo4j
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from normalize import digits, patent_key_from_patent

LINKER_VERSION = "link_v1/0.1"
NOT_IN_USPTO = {"pct", "provisional"}      # these refs can never match a USPTO record


def build_indexes(patents):
    by_grant, by_app, by_pub = {}, {}, {}
    for p in patents:
        key = patent_key_from_patent(p)
        if not key:
            continue
        if p.get("patent_number"):
            by_grant[digits(p["patent_number"])] = (key, p)
        if p.get("application_number"):
            by_app[digits(p["application_number"])] = (key, p)
        if p.get("publication_number"):
            by_pub[p["publication_number"].upper()] = (key, p)
    return by_grant, by_app, by_pub


def match_ref(ref, by_grant, by_app, by_pub):
    """Return a list of candidate matches for one TTO IpRef."""
    out = []
    n = digits(ref.get("number_normalized"))
    t = ref.get("ip_type")

    if t == "granted_patent" and n in by_grant:
        key, _ = by_grant[n]
        out.append({"patent_key": key, "method": "patent_number", "confidence": 1.0, "conflict": None})
    if t == "application" and n in by_app:
        key, _ = by_app[n]
        out.append({"patent_key": key, "method": "application_number", "confidence": 1.0, "conflict": None})

    pub = (ref.get("publication_number") or "").upper()
    if pub and pub in by_pub:
        key, p = by_pub[pub]
        conflict = None
        if t == "application" and p.get("application_number") and digits(p["application_number"]) != n:
            conflict = f"page says application {n}, patent record says {digits(p['application_number'])}"
        if t == "granted_patent" and p.get("patent_number") and digits(p["patent_number"]) != n:
            conflict = f"page says patent {n}, patent record says {digits(p['patent_number'])}"
        out.append({"patent_key": key, "method": "publication_number", "confidence": 0.9, "conflict": conflict})
    return out


def link(technologies, patents):
    """Match every invention to its patents. Returns the list of links (each marked
    confirmed or uncertain, with a confidence number) and a short summary report."""
    by_grant, by_app, by_pub = build_indexes(patents)
    links = {}                                        # (tto_id, patent_key) -> link
    report = {"technologies": len(technologies), "patents": len(patents),
              "refs_total": 0, "refs_not_in_uspto": 0, "refs_without_number": 0,
              "refs_searchable_not_found": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for tech in technologies:
        for i, ref in enumerate(tech["ip_refs"]):
            report["refs_total"] += 1
            if ref.get("ip_type") in NOT_IN_USPTO:
                report["refs_not_in_uspto"] += 1
                continue
            if not ref.get("number_normalized") and not ref.get("publication_number"):
                report["refs_without_number"] += 1
                continue
            cands = match_ref(ref, by_grant, by_app, by_pub)
            if not cands:
                report["refs_searchable_not_found"] += 1
                continue
            for c in cands:
                k = (tech["tto_id"], c["patent_key"])
                l = links.setdefault(k, {
                    "tto_id": tech["tto_id"], "patent_key": c["patent_key"], "methods": [],
                    "confidence": 0.0, "conflicts": [], "evidence_ref": f"{tech['tto_id']}#{i}",
                    "source_page": tech["source"]["page"], "matched_at": now,
                    "linker_version": LINKER_VERSION})
                if c["method"] not in l["methods"]:
                    l["methods"].append(c["method"])
                l["confidence"] = max(l["confidence"], c["confidence"])
                if c["conflict"]:
                    l["conflicts"].append(c["conflict"])

    # Decide status
    for l in links.values():
        exact = any(m in ("patent_number", "application_number") for m in l["methods"])
        l["status"] = "confirmed" if exact or not l["conflicts"] else "uncertain"
        if l["status"] == "uncertain":
            l["confidence"] = 0.5

    # One patent confirmed on several technologies is suspicious, keep it but flag it
    owners = defaultdict(list)
    for l in links.values():
        if l["status"] == "confirmed":
            owners[l["patent_key"]].append(l["tto_id"])
    for l in links.values():
        others = [t for t in owners[l["patent_key"]] if t != l["tto_id"]]
        l["flags"] = [f"patent_also_confirmed_on:{','.join(others)}"] if others else []

    result = sorted(links.values(), key=lambda l: (l["tto_id"], l["patent_key"]))
    confirmed = {l["tto_id"] for l in result if l["status"] == "confirmed"}
    report["links_confirmed"] = sum(l["status"] == "confirmed" for l in result)
    report["links_uncertain"] = sum(l["status"] == "uncertain" for l in result)
    report["technologies_with_confirmed_link"] = len(confirmed)
    return result, report


CONFIRMED_CYPHER = """
MATCH (t:Technology {tto_id: $tto_id}), (p:Patent {patent_key: $patent_key})
MERGE (t)-[l:PROTECTED_BY]->(p)
SET l.match_method = $methods, l.confidence = $confidence, l.evidence_ref = $evidence_ref,
    l.matched_at = $matched_at, l.linker_version = $linker_version, l.flags = $flags
"""

UNCERTAIN_CYPHER = """
MATCH (t:Technology {tto_id: $tto_id}), (p:Patent {patent_key: $patent_key})
MERGE (t)-[l:POSSIBLY_PROTECTED_BY]->(p)
SET l.match_method = $methods, l.confidence = $confidence, l.conflicts = $conflicts,
    l.evidence_ref = $evidence_ref, l.matched_at = $matched_at, l.linker_version = $linker_version,
    l.review_status = coalesce(l.review_status, 'pending')
"""


LINK_FIELDS = ("tto_id", "patent_key", "status", "methods", "confidence", "conflicts",
               "evidence_ref", "matched_at", "linker_version", "flags")
def write_neo4j(links):
    """Save the links into the database: confirmed ones as PROTECTED_BY,
    uncertain ones as POSSIBLY_PROTECTED_BY (so they are never shown as fact)."""
    import config
    from db import neo4j_driver
    with neo4j_driver() as driver, driver.session(database=config.NEO4J_DATABASE) as s:
        for l in links:
            cypher = CONFIRMED_CYPHER if l["status"] == "confirmed" else UNCERTAIN_CYPHER
            params = {k: l[k] for k in LINK_FIELDS}
            s.execute_write(lambda tx: tx.run(cypher, **params).consume())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("technologies")
    ap.add_argument("patents")
    ap.add_argument("-o", "--output", default="links.json")
    ap.add_argument("--neo4j", action="store_true")
    args = ap.parse_args()

    techs = json.load(open(args.technologies, encoding="utf-8"))
    pats = json.load(open(args.patents, encoding="utf-8"))
    links, report = link(techs, pats)
    json.dump({"report": report, "links": links}, open(args.output, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2))
    for l in links:
        print(f"  {l['status']:9} {l['tto_id']} -> {l['patent_key']}  {l['methods']}  {l['conflicts'] or ''}")
    if args.neo4j:
        write_neo4j(links)
        print("links written to Neo4j")
