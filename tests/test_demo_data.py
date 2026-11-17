"""Checks on the demo dataset (data/demo/): real Dartmouth TTO listings + their real
USPTO records. No database and no network needed."""
import json
from pathlib import Path

import pytest

import tto_crawler
from api.main import is_synthetic, patent_url
from link_v1 import link
from load_to_neo4j import patent_params, tto_params

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
TECHS = json.loads((DEMO / "technologies_dartmouth.json").read_text(encoding="utf-8"))
PATS = json.loads((DEMO / "uspto_patents_dartmouth.json").read_text(encoding="utf-8"))
BY_ID = {t["tto_id"]: t for t in TECHS}


def test_both_decks_become_41_technologies():
    ids = [t["tto_id"] for t in TECHS]
    assert len(ids) == 41 and len(set(ids)) == 41
    assert {t["source"]["document"] for t in TECHS} == {"Life-Sciences.pdf", "Physical-Sciences.pdf"}
    # printed in both decks -> one record; printed on two pages of one deck -> one record
    assert BY_ID["2021-026"]["category"] == "Life Sciences / Physical Sciences"
    assert len(BY_ID["2020-039"]["ip_refs"]) == 3


def test_dataset_is_what_the_crawler_produces_from_the_raw_pdfs():
    """Guards against editing the JSON by hand or changing the crawler without rebuilding it."""
    fresh = []
    for pdf in ("Life-Sciences.pdf", "Physical-Sciences.pdf"):
        path = str(ROOT / "data" / "raw" / pdf)
        fresh += tto_crawler.crawl(path, tto_crawler.category_from_file(path))
    fresh = tto_crawler.merge_duplicates(fresh)
    tto_crawler.flag_cross_record_issues(fresh)
    strip = lambda recs: [{**r, "source": {**r["source"], "extracted_at": None}} for r in recs]
    assert strip(fresh) == strip(TECHS)


def test_technologies_follow_the_contract():
    for t in TECHS:
        params = tto_params(t)                       # the loader accepts it
        assert params["title"] and params["description"], t["tto_id"]
        assert params["people"], t["tto_id"]
        assert t["source"]["system"] == "dartmouth_tto" and not is_synthetic(t)


def test_patents_are_real_records_that_follow_the_contract():
    for p in PATS:
        assert patent_params(p)["patent_key"], p["publication_number"]
        assert p["source"]["system"] == "google_patents" and not is_synthetic(p)
        assert p["title"] and p["abstract"] and p["application_number"] and p["inventors"]
        assert patent_url(p).startswith("https://patents.google.com/patent/US")


def test_deck_copy_paste_errors_are_flagged():
    assert "ip_number_shared:PCT/US2024/055039:2020-075,2024-010" in BY_ID["2020-075"]["quality_flags"]
    assert "publication_number_shared:US20240000316A1:2018-168,2021-026" in BY_ID["2018-168"]["quality_flags"]


def test_linking_merges_tto_and_uspto():
    links, report = link(TECHS, PATS)
    status = {(l["tto_id"], l["patent_key"]): l["status"] for l in links}
    assert report["links_confirmed"] == 20 and report["links_uncertain"] == 1
    assert status[("2021-026", "US-11771323")] == "confirmed"          # granted patent
    assert status[("2020-039", "US-APP-17790245")] == "confirmed"      # application
    assert status[("2018-119", "US-12545734")] == "confirmed"          # TTO says application; USPTO has granted it since
    assert status[("2018-168", "US-APP-18229086")] == "uncertain"      # TTO page links another technology's publication
    assert not any(l["tto_id"] == "2022-020" for l in links)           # number printed, no published record found


@pytest.mark.parametrize("label, ip_type, number, flags", [
    ("PCT/US2021/014145", "pct", "PCT/US2021/014145", []),
    ("PENDING APPLICATION PCT/US23/077930", "pct", "PCT/US2023/077930", ["pct_number_short_form"]),
    ("PENDING APPLICATION PCT/US24/33807", "pct", "PCT/US2024/033807", ["pct_number_short_form"]),
    ("US PATENT APPLICATION 17/264,691", "application", "17264691", []),
    ("US PATENT NO 18/359,373", "application", "18359373", ["label_says_patent_but_number_is_application"]),
    ("US PATENT APPLICATION 63/777,912", "provisional", "63777912", ["label_says_application_but_number_is_provisional"]),
    ("US PATENT NO 10,113,979B2", "granted_patent", "10113979", []),
])
def test_crawler_reads_ip_labels(label, ip_type, number, flags):
    ref = tto_crawler.parse_ip_label(label)
    assert (ref["ip_type"], ref["number_normalized"], ref["flags"]) == (ip_type, number, flags)
