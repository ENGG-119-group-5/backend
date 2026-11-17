"""Fetch the real USPTO record behind every US patent and application number printed on
the TTO pages, from its public Google Patents page (robots.txt allows /patent/ pages).

    python src/fetch_patents.py data/demo/technologies_dartmouth.json \
        -o data/demo/uspto_patents_dartmouth.json

Output follows data_contract.md section 3 with source.system = "google_patents".
Pages are cached in data/cache/google_patents/, so a rerun does not touch the network.

How each TTO reference is resolved:
  granted patent -> page US<number>B2 (or B1)
  application    -> the publication the TTO page links to, kept only if its application
                    number is the one printed on the page (the decks have copy-paste errors).
                    If USPTO has granted that application since, the grant is used instead.
  PCT / provisional / no number -> nothing to fetch (not in USPTO, or not public)
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "google_patents"
URL = "https://patents.google.com/patent/{}/en"
EXTRACTOR_VERSION = "fetch_patents/0.1"
DELAY_SECONDS = 1.5          # be polite: one page at a time


def digits(s):
    return re.sub(r"\D", "", s or "")


def page(pub):
    """HTML of one Google Patents page, or None if it does not exist."""
    path = CACHE / f"{pub}.html"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        return text or None
    time.sleep(DELAY_SECONDS)
    req = urllib.request.Request(URL.format(pub), headers={"User-Agent": "vc-dd-pipeline/0.1 (course project)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        text = ""
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")        # cache misses too
    return text or None


def meta(text, name, scheme=None):
    attrs = rf'name="{re.escape(name)}" content="([^"]*)"' + (rf'\s+scheme="{scheme}"' if scheme else r'(?!\s+scheme)')
    return [" ".join(re.sub(r"<[^>]+>", " ", html.unescape(m)).split()) for m in re.findall(rf"<meta {attrs}", text)]


FUNDING = [   # 35 U.S.C. 202(c)(6) wording first, then the looser "this work was supported by ..."
    r"This invention was made with (?:U\.S\. )?(?:government|federal) support.{0,400}?certain rights in (?:the|this) invention\.",
    r"This invention was made with (?:U\.S\. )?(?:government|federal) support.{0,300}?\.(?=\s+[A-Z]|$)",
    r"This (?:work|research) was (?:supported|funded).{0,300}?(?:National Institutes|NIH|National Science Foundation|"
    r"NSF|Department of|DOE|DARPA).{0,200}?\.(?=\s+[A-Z]|$)",
]


def government_interest(text):
    """The federal-funding statement from the description, if the patent has one."""
    body = text[text.find('itemprop="description"'):]
    plain = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())
    for pattern in FUNDING:
        m = re.search(pattern, plain, re.I | re.S)
        if m:
            return m.group(0)
    return None


def granted_as(text):
    """Grant publication (e.g. US12545734B2) listed in this application's own events."""
    m = re.search(r"Publication of (US\d+B\d)\b", re.sub(r"<[^>]+>", " ", text))
    return m.group(1) if m else None


SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def split_name(full):
    """'Robert A. Cramer, Jr.' -> ('Robert A.', 'Cramer'); 'Yina HUANG' -> ('Yina', 'Huang')."""
    tokens = [t.title() if t.isupper() and len(t) > 1 else t for t in full.replace(",", " ").split()]
    while len(tokens) > 2 and tokens[-1].lower() in SUFFIXES:
        tokens.pop()
    return " ".join(tokens[:-1]), tokens[-1]


def record(pub, text, extracted_at):
    """One Google Patents page -> Patent record (data_contract.md section 3)."""
    patent_number = digits((meta(text, "citation_patent_number") or [""])[0]) or None
    names = meta(text, "DC.contributor", "inventor")
    return {
        "schema_version": "0.1",
        "doc_type": "grant" if patent_number else "application",
        "patent_number": patent_number,
        "application_number": digits((meta(text, "citation_patent_application_number") or [""])[0]) or None,
        "publication_number": pub,
        "title": (meta(text, "DC.title") or [None])[0],
        "abstract": (meta(text, "DC.description") or [None])[0],
        "filing_date": (meta(text, "DC.date", "dateSubmitted") or [None])[0],
        "grant_date": (meta(text, "DC.date", "issue") or [None])[0] if patent_number else None,
        "inventors": [dict(zip(("first", "last"), split_name(n)), city=None, state=None, country=None)
                      for n in names],
        "assignees": [{"name": n} for n in meta(text, "DC.contributor", "assignee")],
        "government_interest": government_interest(text),
        "source": {"system": "google_patents", "document": pub, "source_url": URL.format(pub),
                   "extracted_at": extracted_at, "extractor_version": EXTRACTOR_VERSION},
        "quality_flags": [],
    }


def resolve(ref):
    """TTO IpRef -> (publication number, note) of the USPTO document it refers to."""
    n, kind = digits(ref.get("number_normalized")), ref.get("ip_type")
    if kind == "granted_patent":
        for pub in (f"US{n}B2", f"US{n}B1"):
            if page(pub):
                return pub, "grant"
        return None, "grant page not found"
    if kind != "application":
        return None, None
    pub = ref.get("publication_number")
    text = page(pub) if pub else None
    if not text:
        return None, "no publication linked on the TTO page" if not pub else f"{pub} not found"
    found = digits((meta(text, "citation_patent_application_number") or [""])[0])
    if found != n:
        return None, f"TTO page links {pub}, which is application {found}, not {n}"
    grant = granted_as(text)
    grant_text = page(grant) if grant else None
    if grant_text and digits((meta(grant_text, "citation_patent_application_number") or [""])[0]) == n:
        return grant, f"granted since the TTO listing ({pub} -> {grant})"
    return pub, "application"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("technologies")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    techs = json.loads(Path(args.technologies).read_text(encoding="utf-8"))
    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records, missing = {}, 0
    for t in techs:
        for ref in t["ip_refs"]:
            pub, note = resolve(ref)
            if note is None:
                continue
            print(f"{t['tto_id']:10} {ref['raw_label'][:45]:45} -> {pub or '-':17} {note}")
            if pub:
                records.setdefault(pub, record(pub, page(pub), extracted_at))
            else:
                missing += 1
    out = sorted(records.values(), key=lambda r: r["publication_number"])
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    grants = sum(r["doc_type"] == "grant" for r in out)
    print(f"\n{len(out)} USPTO records ({grants} grants, {len(out) - grants} applications) -> {args.output}; "
          f"{missing} references not resolved")
    sys.exit(0)
