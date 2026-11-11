"""API tests: /search and /technology/{id} against Neo4j loaded with the fixtures.

Assertions only rely on the fixture records (29 Life Sciences technologies and
4 fake patents), so they still hold if the database also has other data.

Expected IP scores with the fixtures (rubric-v0, no patent dates -> recency 0):
  2018-168  grant + application, 2 links          -> 65.0
  2021-023  application only, funding statement   -> 60.0
  2004-0269 no confirmed link, available          -> 10.0
"""
import pytest

from . import scoring_helpers as h


# ------------------------------------------------------------------- /search
def test_empty_query_lists_technologies_by_ip_score(client):
    r = client.get("/search", params={"q": "", "type": "technology", "limit": 100})
    assert r.status_code == 200
    body = r.json()
    hits = body["hits"]
    assert body["total"] >= 29
    assert {hit["type"] for hit in hits} == {"technology"}
    scores = [hit["ipScore"] for hit in hits]
    assert scores == sorted(scores, reverse=True)

    rank = {hit["id"]: i for i, hit in enumerate(hits)}
    assert rank["2018-168"] < rank["2021-023"] < rank["2004-0269"]
    by_id = {hit["id"]: hit for hit in hits}
    assert by_id["2018-168"]["ipScore"] == pytest.approx(65.0)
    assert by_id["2021-023"]["ipScore"] == pytest.approx(60.0)
    assert by_id["2004-0269"]["ipScore"] == pytest.approx(10.0)


def test_keyword_match_in_title(client):
    hits = client.get("/search", params={"q": "dielectric", "type": "technology"}).json()["hits"]
    hit = next(x for x in hits if x["id"] == "2018-168")
    assert hit["relevance"] == 1.0
    assert hit["title"].startswith("Non-Invasive Dielectric Probe")
    assert "ipScore" in hit and "snippet" in hit


def test_multiple_keywords_must_all_match(client):
    ids = {x["id"] for x in client.get("/search", params={"q": "dielectric wine", "type": "technology"}).json()["hits"]}
    assert "2018-168" in ids
    ids = {x["id"] for x in client.get("/search", params={"q": "dielectric immunotherapy", "type": "technology"}).json()["hits"]}
    assert "2018-168" not in ids


def test_type_filter(client):
    hits = client.get("/search", params={"q": "", "type": "patent", "limit": 100}).json()["hits"]
    assert hits and {x["type"] for x in hits} == {"patent"}
    assert all("ipScore" not in x for x in hits)


def test_limit(client):
    body = client.get("/search", params={"q": "", "type": "technology", "limit": 3}).json()
    assert len(body["hits"]) == 3
    assert body["total"] >= 29


@pytest.mark.parametrize("params", [{"type": "company"}, {"limit": 0}, {"limit": 101}])
def test_invalid_parameters_are_422(client, params):
    assert client.get("/search", params=params).status_code == 422


# ------------------------------------------------------------ /technology/{id}
def test_technology_detail(client):
    r = client.get("/technology/2018-168")
    assert r.status_code == 200
    t = r.json()

    # camelCase on the wire (API_CONTRACT.md)
    for key in ("ttoCaseNumber", "ipScore", "auditLog", "publishedAt"):
        assert key in t
    assert t["id"] == t["ttoCaseNumber"] == "2018-168"
    assert t["status"] == "available"
    assert t["categories"] == ["Life Sciences"]
    assert t["sources"][0]["kind"] == "tto"

    patents = {p["id"]: p for p in t["patents"]}
    assert set(patents) == {"US-10113979", "US-APP-17264691"}
    assert all(p["link"]["method"] == "patent_number" for p in patents.values())
    assert all(p["link"]["confidence"] == 1.0 for p in patents.values())

    names = {i["name"]: i["affiliation"] for i in t["inventors"]}
    assert names == {"Paul M. Meaney": "Professor of Engineering",
                     "Timothy Raynolds": "Retired Research Engineer"}   # USPTO duplicates merged by name_key


def test_technology_score_breakdown_follows_contract(client):
    score = client.get("/technology/2018-168").json()["ipScore"]
    h.assert_contract_rules(score)
    assert score["computed"] == pytest.approx(65.0)
    assert score["override"] is None and score["effective"] == score["computed"]


def test_uncertain_link_is_not_shown_as_a_patent(client):
    # 2021-026 only reaches US-APP-17264691 through a conflicting publication number:
    # that is POSSIBLY_PROTECTED_BY (review queue), never a confirmed patent.
    t = client.get("/technology/2021-026").json()
    assert t["patents"] == []
    assert t["ipScore"]["computed"] == pytest.approx(10.0)


def test_unknown_technology_is_404(client):
    r = client.get("/technology/does-not-exist")
    assert r.status_code == 404
    assert "does-not-exist" in r.json()["detail"]
