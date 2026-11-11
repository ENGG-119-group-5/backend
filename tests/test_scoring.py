"""Unit tests for the rule-based IP score (src/api/scoring.py). No database needed."""
from datetime import date

import pytest

from . import scoring_helpers as h
from api.scoring import RUBRIC, WEIGHTS, compute_ip_score

TODAY = date(2026, 11, 11)   # fixed, so recency does not depend on when the tests run


def patent(doc_type="grant", grant_date=None, filing_date=None, funding=False, confidence=1.0):
    return {"doc_type": doc_type, "number_label": "US 1", "url": "https://patents.google.com/patent/US1",
            "grant_date": grant_date, "filing_date": filing_date, "has_funding": funding,
            "confidence": confidence}


def test_rubric_weights_are_unchanged():
    assert RUBRIC == "rubric-v0"
    assert WEIGHTS == {"protection": 0.30, "link_conf": 0.15, "links": 0.15,
                       "funding": 0.15, "availability": 0.10, "recency": 0.15}


@pytest.mark.parametrize("patents", [[], [patent()], [patent("application", funding=True)],
                                     [patent(grant_date="2024-05-01"), patent("application")]])
def test_contract_rules_hold(patents):
    h.assert_contract_rules(compute_ip_score("available", patents, today=TODAY))


def test_grant_beats_application_beats_nothing():
    grant = compute_ip_score("available", [patent("grant")], today=TODAY)["computed"]
    app = compute_ip_score("available", [patent("application")], today=TODAY)["computed"]
    none = compute_ip_score("available", [], today=TODAY)["computed"]
    assert grant > app > none == 10.0


def test_recency_uses_the_given_date():
    s = compute_ip_score("available", [patent(grant_date="2021-03-02")], today=TODAY)
    recency = next(i for i in s["indicators"] if i["key"] == "recency")
    assert recency["normalized"] == pytest.approx(0.5)   # 2021 is 5 of the last 10 years
    assert recency["value"] == "Latest patent date 2021"


def test_override_sets_effective_score():
    s = compute_ip_score("available", [], {"score": 72.44, "reason": "r", "analyst": "a", "at": "t"}, today=TODAY)
    assert s["effective"] == s["override"]["score"] == 72.4   # rounded to 1 decimal
    assert s["computed"] == 10.0
