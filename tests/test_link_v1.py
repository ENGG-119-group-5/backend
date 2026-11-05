"""
Tests for linking v1 on the hand-made fixtures.
Run:  pytest test_link_v1.py      (or: python test_link_v1.py)
"""

import json
import os

from link_v1 import link
from normalize import name_key, patent_key_from_ref

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
TECHS = json.load(open(os.path.join(FIXTURES, "technologies_life_sciences.json"), encoding="utf-8"))
PATS = json.load(open(os.path.join(FIXTURES, "uspto_patents_test.json"), encoding="utf-8"))
LINKS, REPORT = link(TECHS, PATS)


def find(tto_id, patent_key):
    return next((l for l in LINKS if l["tto_id"] == tto_id and l["patent_key"] == patent_key), None)


def test_granted_patent_links_by_number():
    l = find("2018-168", "US-10113979")
    assert l and l["status"] == "confirmed" and "patent_number" in l["methods"]


def test_mislabeled_application_still_links():
    # TTO page says "US PATENT NO 18/359,373", but it is an application
    l = find("2021-023", "US-APP-18359373")
    assert l and l["status"] == "confirmed" and "application_number" in l["methods"]


def test_copy_paste_conflict_goes_to_review():
    assert find("2018-168", "US-APP-17264691")["status"] == "confirmed"
    l = find("2021-026", "US-APP-17264691")
    assert l and l["status"] == "uncertain" and l["conflicts"]


def test_negative_control_has_no_link():
    assert not any(l["patent_key"] == "US-99999999" for l in LINKS)


def test_pct_and_provisional_are_never_searched():
    assert REPORT["refs_not_in_uspto"] == 12


def test_name_key():
    assert name_key("Dr. Randolph J. Noelle") == "randolph noelle"
    assert name_key("George A. O’Toole") == "george otoole"
    assert name_key("Lucas Salas, MD, PhD") == "lucas salas"


def test_patent_keys():
    assert patent_key_from_ref({"ip_type": "application", "number_normalized": "17264691"}) == "US-APP-17264691"
    assert patent_key_from_ref({"ip_type": "granted_patent", "number_normalized": "10113979"}) == "US-10113979"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"{len(tests)} tests passed")
