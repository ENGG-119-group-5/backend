"""Assertions shared by the scoring and API tests (docs: API_CONTRACT.md, IP-score rules)."""
import pytest

from api.scoring import WEIGHTS


def assert_contract_rules(score: dict) -> None:
    indicators = score["indicators"]
    assert {i["key"]: i["weight"] for i in indicators} == WEIGHTS
    assert sum(i["weight"] for i in indicators) == pytest.approx(1.0)
    for i in indicators:
        assert 0.0 <= i["normalized"] <= 1.0
        assert i["contribution"] == pytest.approx(round(i["normalized"] * i["weight"] * 100, 1))
    assert score["computed"] == pytest.approx(round(sum(i["contribution"] for i in indicators), 1))
