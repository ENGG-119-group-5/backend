"""Checks on the synthetic demo dataset (data/demo/). No database needed."""
import json
from pathlib import Path

from link_v1 import link
from load_to_neo4j import patent_params, tto_params
from api.main import is_synthetic, patent_url

DEMO = Path(__file__).resolve().parent.parent / "data" / "demo"
TECHS = json.loads((DEMO / "technologies_demo.json").read_text(encoding="utf-8"))
PATS = json.loads((DEMO / "uspto_patents_demo.json").read_text(encoding="utf-8"))


def test_every_record_is_flagged_synthetic():
    for rec in TECHS + PATS:
        assert rec["source"]["system"] == "synthetic"
        assert "synthetic" in rec["quality_flags"]


def test_technologies_follow_the_contract():
    ids = [t["tto_id"] for t in TECHS]
    assert len(ids) == 30 and len(set(ids)) == 30
    for t in TECHS:
        params = tto_params(t)                       # the loader accepts it
        assert params["title"] and params["description"]
        assert params["people"], t["tto_id"]


def test_patents_follow_the_contract():
    for p in PATS:
        assert patent_params(p)["patent_key"], p["title"]   # every patent gets a key


def test_linking_merges_tto_and_uspto():
    links, report = link(TECHS, PATS)
    status = {(l["tto_id"], l["patent_key"]): l["status"] for l in links}
    assert report["links_confirmed"] == 17
    assert status[("DEMO-01", "US-12104417")] == "confirmed"           # granted patent
    assert status[("DEMO-02", "US-APP-18623905")] == "confirmed"       # application
    assert status[("DEMO-08", "US-APP-18623905")] == "uncertain"       # copy-paste publication number
    assert not any(l["tto_id"] == "DEMO-20" for l in links)            # number printed but no USPTO record


def test_synthetic_patents_never_link_to_real_patent_pages():
    grant = next(p for p in PATS if p["doc_type"] == "grant")
    assert is_synthetic(grant)
    assert patent_url(grant) is None
    assert patent_url({**grant, "quality_flags": []}).startswith("https://patents.google.com/")
