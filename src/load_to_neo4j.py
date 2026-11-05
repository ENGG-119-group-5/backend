"""
Load data_contract.md records into Neo4j. Rerunnable: every write is a MERGE
on a unique key, so running the script twice creates no duplicates.

Usage:
    pip install neo4j
    export NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=...

    python load_to_neo4j.py schema                              # constraints, run once
    python load_to_neo4j.py tto technologies_life_sciences.json # TTO side
    python load_to_neo4j.py patents uspto_patents.json          # USPTO side (or test fixtures)

    Add --dry-run to print the Cypher and parameters without a database.
"""

import argparse
import json
import os

from normalize import name_key, patent_key_from_patent, patent_key_from_ref, tto_inventor_id

SCHEMA = [
    "CREATE CONSTRAINT technology_id IF NOT EXISTS FOR (t:Technology) REQUIRE t.tto_id IS UNIQUE",
    "CREATE CONSTRAINT patent_key IF NOT EXISTS FOR (p:Patent) REQUIRE p.patent_key IS UNIQUE",
    "CREATE CONSTRAINT ipref_key IF NOT EXISTS FOR (r:IpRef) REQUIRE r.ref_key IS UNIQUE",
    "CREATE CONSTRAINT inventor_id IF NOT EXISTS FOR (i:Inventor) REQUIRE i.inventor_id IS UNIQUE",
    "CREATE CONSTRAINT assignee_name IF NOT EXISTS FOR (a:Assignee) REQUIRE a.name_normalized IS UNIQUE",
]

# One technology per call. SET (not CREATE) on properties = rerun updates, never duplicates.
# FOREACH (not UNWIND): a technology with no IP refs or no people must still be written.
TTO_CYPHER = """
MERGE (t:Technology {tto_id: $tto_id})
SET t.title = $title, t.category = $category, t.status = $status, t.rights = $rights,
    t.description = $description, t.advantages = $advantages,
    t.source_document = $source_document, t.source_page = $source_page,
    t.extracted_at = $extracted_at, t.quality_flags = $quality_flags
FOREACH (ref IN $ip_refs |
  MERGE (r:IpRef {ref_key: ref.ref_key})
  SET r.raw_label = ref.raw_label, r.ip_type = ref.ip_type, r.patent_key = ref.patent_key,
      r.number_normalized = ref.number_normalized, r.publication_number = ref.publication_number,
      r.google_patents_url = ref.google_patents_url, r.flags = ref.flags
  MERGE (t)-[:CLAIMS_IP]->(r)
)
FOREACH (p IN $people |
  MERGE (i:Inventor {inventor_id: p.inventor_id})
  SET i.name = p.name, i.name_key = p.name_key, i.source = 'tto', i.profile_url = p.profile_url
  MERGE (i)-[l:LISTED_ON]->(t)
  SET l.role = p.role, l.title_affiliation = p.title_affiliation
)
"""

PATENT_CYPHER = """
MERGE (p:Patent {patent_key: $patent_key})
SET p.doc_type = $doc_type, p.patent_number = $patent_number,
    p.application_number = $application_number, p.publication_number = $publication_number,
    p.title = $title, p.abstract = $abstract, p.filing_date = $filing_date, p.grant_date = $grant_date,
    p.government_interest = $government_interest, p.source_system = $source_system,
    p.quality_flags = $quality_flags
FOREACH (inv IN $inventors |
  MERGE (i:Inventor {inventor_id: inv.inventor_id})
  SET i.name = inv.name, i.name_key = inv.name_key, i.source = 'uspto',
      i.city = inv.city, i.state = inv.state, i.country = inv.country
  MERGE (i)-[:INVENTED]->(p)
)
FOREACH (a IN $assignees |
  MERGE (asg:Assignee {name_normalized: a.name_normalized})
  SET asg.name = a.name
  MERGE (p)-[:ASSIGNED_TO]->(asg)
)
"""


def tto_params(rec):
    refs = []
    for i, ref in enumerate(rec["ip_refs"]):
        pk = patent_key_from_ref(ref)
        refs.append({
            "ref_key": f"{rec['tto_id']}#{i}",          # one IpRef per line printed on the page
            "raw_label": ref.get("raw_label"), "ip_type": ref.get("ip_type"), "patent_key": pk,
            "number_normalized": ref.get("number_normalized"),
            "publication_number": ref.get("publication_number"),
            "google_patents_url": ref.get("google_patents_url"), "flags": ref.get("flags", []),
        })
    people = [{
        "inventor_id": tto_inventor_id(p["name"]), "name": p["name"], "name_key": name_key(p["name"]),
        "role": p["role"], "title_affiliation": p.get("title_affiliation"), "profile_url": p.get("profile_url"),
    } for p in rec["people"]]
    return {
        "tto_id": rec["tto_id"], "title": rec["title"], "category": rec.get("category"),
        "status": rec.get("status"), "rights": rec.get("rights"), "description": rec.get("description"),
        "advantages": rec.get("advantages", []),
        "source_document": rec["source"]["document"], "source_page": rec["source"]["page"],
        "extracted_at": rec["source"]["extracted_at"], "quality_flags": rec.get("quality_flags", []),
        "ip_refs": refs, "people": people,
    }


def patent_params(p):
    inventors = []
    for inv in p.get("inventors", []):
        full = f"{inv.get('first', '')} {inv.get('last', '')}".strip()
        # USPTO has no stable person id in our MVP: key = name + city. Resolution (SAME_AS) comes in v2.
        inventors.append({
            "inventor_id": f"uspto:{name_key(full)}|{(inv.get('city') or '').lower()}",
            "name": full, "name_key": name_key(full),
            "city": inv.get("city"), "state": inv.get("state"), "country": inv.get("country"),
        })
    assignees = [{"name": a["name"], "name_normalized": " ".join(a["name"].lower().split())}
                 for a in p.get("assignees", [])]
    return {
        "patent_key": patent_key_from_patent(p), "doc_type": p.get("doc_type"),
        "patent_number": p.get("patent_number"), "application_number": p.get("application_number"),
        "publication_number": p.get("publication_number"), "title": p.get("title"),
        "abstract": p.get("abstract"), "filing_date": p.get("filing_date"), "grant_date": p.get("grant_date"),
        "government_interest": p.get("government_interest"),
        "source_system": p.get("source", {}).get("system"), "quality_flags": p.get("quality_flags", []),
        "inventors": inventors, "assignees": assignees,
    }


def run(statements, dry_run):
    """statements: list of (cypher, params)."""
    if dry_run:
        for cypher, params in statements:
            print(cypher.strip().splitlines()[0], "...", json.dumps(params, ensure_ascii=False)[:200])
        print(f"[dry-run] {len(statements)} statements")
        return
    from neo4j import GraphDatabase   # imported here so --dry-run works without the driver
    driver = GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                                  auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]))
    with driver.session() as session:
        for cypher, params in statements:
            session.execute_write(lambda tx: tx.run(cypher, **params).consume())
    driver.close()
    print(f"{len(statements)} statements written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["schema", "tto", "patents"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.what == "schema":
        run([(c, {}) for c in SCHEMA], args.dry_run)
    else:
        records = json.load(open(args.file, encoding="utf-8"))
        if args.what == "tto":
            run([(TTO_CYPHER, tto_params(r)) for r in records], args.dry_run)
        else:
            stmts, skipped = [], 0
            for p in records:
                params = patent_params(p)
                if params["patent_key"] is None:
                    skipped += 1
                    continue
                stmts.append((PATENT_CYPHER, params))
            run(stmts, args.dry_run)
            if skipped:
                print(f"{skipped} patent records skipped (no patent or application number)")
