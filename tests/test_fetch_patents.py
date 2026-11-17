"""fetch_patents.py parsing, on a tiny hand-written page (no network)."""
import pytest

import fetch_patents as fp

PAGE = """<html><head>
<meta name="DC.title" content="Systems for testing
   things &amp; more">
<meta name="DC.description" content="  An example abstract.  ">
<meta name="DC.date" content="2021-01-29" scheme="dateSubmitted">
<meta name="citation_patent_application_number" content="US:17/264,691">
<meta name="citation_patent_number" content="US:11000001">
<meta name="DC.date" content="2023-05-02" scheme="issue">
<meta name="DC.contributor" content="Robert A. Cramer, Jr." scheme="inventor">
<meta name="DC.contributor" content="Yina HUANG" scheme="inventor">
<meta name="DC.contributor" content="Dartmouth College" scheme="assignee">
</head><body>
<dd itemprop="events"><time>2023-05-02</time> Publication of US11000001B2 publication</dd>
<section itemprop="description"><p>This invention was made with government support under Grant No. R01 CA000000
awarded by the National Institutes of Health. The government has certain rights in the invention.</p></section>
</body></html>"""


def test_record_follows_the_contract():
    r = fp.record("US11000001B2", PAGE, "2026-11-17T00:00:00+00:00")
    assert r["doc_type"] == "grant" and r["patent_number"] == "11000001" and r["application_number"] == "17264691"
    assert r["title"] == "Systems for testing things & more" and r["abstract"] == "An example abstract."
    assert (r["filing_date"], r["grant_date"]) == ("2021-01-29", "2023-05-02")
    assert [(i["first"], i["last"]) for i in r["inventors"]] == [("Robert A.", "Cramer"), ("Yina", "Huang")]
    assert r["assignees"] == [{"name": "Dartmouth College"}]
    assert r["government_interest"].endswith("The government has certain rights in the invention.")
    assert "Grant No. R01" in r["government_interest"]        # not cut at the period in "No."
    assert r["source"]["system"] == "google_patents"


def test_application_page_has_no_grant_fields():
    app = PAGE.replace('<meta name="citation_patent_number" content="US:11000001">', "")
    r = fp.record("US20210000001A1", app, "2026-11-17T00:00:00+00:00")
    assert r["doc_type"] == "application" and r["patent_number"] is None and r["grant_date"] is None


def test_granted_as_reads_this_applications_events():
    assert fp.granted_as(PAGE) == "US11000001B2"
    assert fp.granted_as("<html>Publication of US20210000001A1</html>") is None


@pytest.mark.parametrize("text", ["<section itemprop=\"description\">No funding statement.</section>", ""])
def test_no_funding_statement(text):
    assert fp.government_interest(text) is None
