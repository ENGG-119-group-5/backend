"""Thesis matcher tests. No API key and no network: the Claude call is replaced by a fake."""
import json

import pytest

import api.main as main
from api import matcher

INVENTION = {
    "tto_id": "X-1", "title": "Armored CAR T Cells", "category": "Life Sciences", "status": "available_for_license",
    "rights": "us_and_china",
    "description": "Stage: preclinical; tumors cleared in two mouse models.",
    "advantages": ["Works with any CAR target."], "features": ["Cleared ovarian tumors in mice."],
    "looking_for": ["Exclusive license."],
    "refs": [{"raw_label": "US PATENT NO 12,104,417", "ip_type": "granted_patent"}],
    "patents": [{"patent_key": "US-12104417", "doc_type": "grant", "title": "Inducible cytokine switch",
                 "abstract": "Engineered T cells.", "grant_date": "2024-10-01", "government_interest": "NIH grant",
                 "assignees": ["Dartmouth College", "Celdara Medical LLC"]}],
    "people": ["Elena Marsh (Associate Professor)"],
}


# ----------------------------------------------------------------- pure functions
def test_invention_text_merges_tto_and_uspto():
    text = matcher.invention_text(INVENTION)
    for expected in ("### X-1: Armored CAR T Cells", "Stage: preclinical", "Details: Cleared ovarian tumors in mice.",
                     "Looking for: Exclusive license.",
                     "US PATENT NO 12,104,417 (granted patent)", "USPTO record US-12104417 (granted patent, granted 2024-10-01)",
                     "Federally funded.", "Assignees: Dartmouth College; Celdara Medical LLC.",
                     "Rights available: us and china.", "Elena Marsh"):
        assert expected in text
    bare = matcher.invention_text({"tto_id": "X-2", "title": "T", "refs": [], "patents": []})
    assert "IP listed by the TTO: none listed" in bare and "no confirmed patent" in bare


@pytest.mark.parametrize("quote, found", [
    ("tumors cleared in two mouse models", True),
    ("  Tumors   cleared in TWO mouse models. ", True),   # case, spaces and end punctuation ignored
    ("tumors cleared in three mouse models", False),      # changed word
    ("mouse", False),                                     # too short to count as evidence
    ("", False),
])
def test_quote_found(quote, found):
    assert matcher.quote_found(quote, matcher.invention_text(INVENTION)) is found


def test_rank_orders_by_label_then_total_then_ip_score():
    m = lambda title, label, total, ip=None: {"technology": {"title": title, "ipScore": ip}, "label": label, "totalScore": total}
    ranked = matcher.rank([m("a", "none", 8), m("b", "potential", 3), m("c", "strong", 6),
                           m("d", "strong", 8, 70.5), m("e", "strong", 8, 87.0)])
    assert [x["technology"]["title"] for x in ranked] == ["e", "d", "c", "b", "a"]


def test_skipped_inventions_get_a_second_call(monkeypatch):
    import asyncio
    calls = []

    async def fake_score(claude, pdf, inventions):
        ids = [i["tto_id"] for i in inventions]
        calls.append(ids)
        first_call = len(calls) == 1
        return matcher.MatchOutput(thesis_summary="t", verdicts=[
            matcher.Verdict(invention_id=i, label="none", area=fit(0), problem=fit(0), stage=fit(0), deal=fit(0),
                            summary="s") for i in (ids[:1] if first_call else ids + ["A"])])   # skips; then repeats A
    monkeypatch.setattr(matcher, "score", fake_score)

    out = asyncio.run(matcher.run_match(None, b"%PDF", [{"tto_id": "A"}, {"tto_id": "B"}, {"tto_id": "C"}]))
    assert calls == [["A", "B", "C"], ["B", "C"]]                      # only the skipped ones are asked again
    assert [v.invention_id for v in out.verdicts] == ["A", "B", "C"]   # and nothing is duplicated


# -------------------------------------------------------- /match and /samples (need Neo4j + fixtures)
PDF = b"%PDF-1.4 fake thesis"


def fit(score, quote=""):
    return matcher.FitCheck(score=score, reason="r", quote=quote)


def fake_output():
    return matcher.MatchOutput(thesis_summary="Wants wine-testing devices.", verdicts=[
        matcher.Verdict(invention_id="2018-168", label="strong", area=fit(2, "Dielectric Probe for Testing Closed Bottles of Wine"),
                        problem=fit(2), stage=fit(1), deal=fit(2, "this sentence is not in the record"), summary="s"),
        matcher.Verdict(invention_id="2021-023", label="none", area=fit(0), problem=fit(0), stage=fit(0), deal=fit(0), summary="s"),
        matcher.Verdict(invention_id="not-a-real-id", label="strong", area=fit(2), problem=fit(2), stage=fit(2), deal=fit(2), summary="s"),
    ])


def test_live_match_uses_claude_output_and_verifies_quotes(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(main, "RESULTS_DIR", main.DEMO_DIR / "no-such-dir")

    async def fake_run_match(claude, pdf, inventions):
        assert pdf == PDF and any(i["tto_id"] == "2018-168" for i in inventions)
        return fake_output()
    monkeypatch.setattr(matcher, "run_match", fake_run_match)

    r = client.post("/match", files={"file": ("my thesis.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "live" and body["thesisName"] == "my thesis.pdf"
    top = body["matches"][0]
    assert top["technology"]["id"] == "2018-168" and top["label"] == "strong" and top["totalScore"] == 7
    assert top["technology"]["ipScore"] == pytest.approx(65.0)
    quotes = {f["key"]: f["quoteVerified"] for f in top["fits"]}
    assert quotes == {"area": True, "problem": False, "stage": False, "deal": False}
    assert [m["technology"]["id"] for m in body["matches"]] == ["2018-168", "2021-023"]   # unknown id dropped
    assert "2004-0269" in body["unassessedIds"]                                          # never filled in


def test_saved_result_is_returned_without_a_key(client, monkeypatch, tmp_path):
    import hashlib
    saved = {"thesisName": "s.pdf", "thesisSha256": hashlib.sha256(PDF).hexdigest(), "thesisSummary": "x",
             "model": "claude-opus-5-5", "source": "live", "generatedAt": "2026-11-17T00:00:00+00:00",
             "matches": [], "unassessedIds": []}
    (tmp_path / "s.json").write_text(json.dumps(saved))
    monkeypatch.setattr(main, "RESULTS_DIR", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = client.post("/match", files={"file": ("s.pdf", PDF, "application/pdf")})
    assert r.status_code == 200 and r.json()["source"] == "saved_demo"


def test_new_thesis_without_a_key_is_503(client, monkeypatch):
    monkeypatch.setattr(main, "RESULTS_DIR", main.DEMO_DIR / "no-such-dir")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = client.post("/match", files={"file": ("t.pdf", PDF, "application/pdf")})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_non_pdf_is_422(client):
    r = client.post("/match", files={"file": ("t.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_samples(client):
    names = [s["name"] for s in client.get("/samples").json()]
    assert names == list(main.SAMPLES)
    r = client.get(f"/samples/{names[0]}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get("/samples/..%2F..%2F.env").status_code == 404
