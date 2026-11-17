"""
Dartmouth TTO licensing PDF crawler (POC, v0.1)

Reads a Dartmouth Technology Transfer "Technology Available for Licensing"
PDF (one technology per page) and outputs Technology records that follow
data_contract.md (schema_version 0.1).

Usage:
    pip install pdfplumber
    python tto_crawler.py Life-Sciences.pdf --category "Life Sciences" -o technologies.json
    python tto_crawler.py Life-Sciences.pdf Physical-Sciences.pdf -o technologies.json
        (several PDFs: category comes from each file name; a technology listed twice,
         in one deck or across decks, is merged into one record)

Design notes:
- Text is read with use_text_flow=True (InDesign content order). This gives
  clean reading order and avoids broken words like "P atricia".
- Header fields (ID, status, IP labels) and Google Patents links are read by
  position (top-left box of the page).
- Nothing is guessed: unclear values are kept raw and listed in quality_flags.
"""

import argparse
import json
import re
from datetime import datetime, timezone

import pdfplumber

EXTRACTOR_VERSION = "tto_crawler/0.1"
SOURCE_URL = "https://tto.dartmouth.edu/engage-us/licensing-opportunities"

HEADER_BOX = (0, 0, 185, 92)        # ID, status, IP labels
PEOPLE_BAND = (0, 88, None, 126)    # PI / co-inventor lines
CONTACT_BAND = (330, 490, None, 540)

SECTION_HEADINGS = {
    "DESCRIPTION": "description",
    "DESCRIPTON": "description",            # typo exists in the source PDF
    "INVENTION OVERVIEW": "description",
    "ADVANTAGES": "advantages",
    "ADVANTAGES AND BENEFITS": "advantages",
    "ADVANTAGES AND SCOPE": "advantages",
    "FEATURES AND ADVANTAGES": "advantages",
    "ADVANTAGES / SCOPE": "advantages",
    "KEY ADVANTAGES": "advantages",
    "FEATURES": "features",
    "FEATURES AND BENEFITS": "features",
    "FEATURES AND OPERATING PRINCIPLES": "features",
    "FEATURES / OPERATING PRINCIPLES (CONT.)": "features",
    "FEATURES / OPERATING PRINCIPALS": "features",   # typo exists in the source PDF
    "MORE DETAILS": "details",
    "EFFICACY": "efficacy",
    "LOOKING FOR": "looking_for",
}

# Lines that end a section (captions, footer, header text)
STOP_PATTERNS = [
    r"^Figure", r"^Source:", r"^CONTACTS?:", r"^PRINCIPAL INVESTIGATOR",
    r"^CO-INVENTORS", r"^GRADUATE STUDENTS", r"^\d{4}-\d{3,4}$",
    r"^AVAILABLE FOR", r"^EXTENSIVE IP", r"^VIEW PUBLICATIONS?$",
    r"\|\s*\(\d{3}\)",                       # contact line "Name | (802) ..."
]

ROLE_LABELS = {
    "PRINCIPAL INVESTIGATOR": "principal_investigator",
    "PRINCIPAL INVESTIGATORS": "principal_investigator",
    "CO-INVENTORS": "co_inventor",
    "CO-INVENTOR": "co_inventor",
    "GRADUATE STUDENTS": "graduate_student",
}

DEGREES = {"PH.D.", "PHD", "MD", "MPH", "MD/PHD", "PH.D"}


# ---------- small helpers ----------

def crop(page, box):
    x0, top, x1, bottom = box
    return page.crop((x0, top, x1 if x1 is not None else page.width, bottom))


def flow_text(page_or_crop):
    return page_or_crop.extract_text(use_text_flow=True) or ""


def clean(s):
    return re.sub(r"\s+", " ", s).strip()


# ---------- header: ID, status, rights, IP references ----------

def parse_ip_label(label):
    """Classify one IP line from the header box. Returns a dict (ip_ref)."""
    ref = {"raw_label": label, "ip_type": "unknown", "country": None,
           "number_normalized": None, "publication_number": None,
           "google_patents_url": None, "flags": []}
    up = label.upper()

    pct = re.search(r"PCT/([A-Z]{2})(\d{4}|\d{2})/(\d{5,6})", up)
    if pct:
        year, serial = pct.group(2), pct.group(3)
        ref.update(ip_type="pct", country="WO",
                   number_normalized=f"PCT/{pct.group(1)}{year if len(year) == 4 else '20' + year}/{serial.zfill(6)}")
        if len(year) == 2 or len(serial) == 5:          # "PCT/US23/077930", "PCT/US24/33807"
            ref["flags"].append("pct_number_short_form")
        return ref

    num = re.search(r"(?:US)?\s*(\d{2})\s*/\s*([\d,]+)", up)       # 17/264,691
    if num:
        series, rest = num.group(1), num.group(2).replace(",", "")
        ref["country"] = "US"
        ref["number_normalized"] = series + rest
        if series in {"60", "61", "62", "63"}:
            ref["ip_type"] = "provisional"
            if "PROVISIONAL" not in up:
                ref["flags"].append("label_says_application_but_number_is_provisional")
        else:
            ref["ip_type"] = "application"
            if "APPLICATION" not in up:
                ref["flags"].append("label_says_patent_but_number_is_application")
        return ref

    digits = re.search(r"([\d,]{7,})", up)
    if digits:
        n = digits.group(1).replace(",", "")
        ref["country"] = "US"
        ref["number_normalized"] = n
        ref["ip_type"] = "application" if "APPLICATION" in up else "granted_patent"
        if ref["ip_type"] == "application":
            ref["flags"].append("application_number_missing_slash")
    return ref


def parse_header(page):
    box = crop(page, HEADER_BOX)
    lines = [clean(l) for l in (box.extract_text() or "").splitlines() if clean(l)]
    out = {"tto_id": None, "status": None, "rights": None, "ip_refs": [], "flags": []}

    for line in lines:
        up = line.upper()
        if re.fullmatch(r"\d{4}-\d{3,4}", line):
            out["tto_id"] = line
        elif "AVAILABLE FOR LICENSE" in up:
            out["status"] = "available_for_license"
        elif "EXTENSIVE IP PORTFOLIO" in up or "AVAILABLE FOR REVIEW" in up:
            out["status"] = "portfolio_available_for_review"
        elif "WORLDWIDE RIGHTS" in up:
            out["rights"] = "worldwide"
        elif "US AND CHINA RIGHTS" in up:
            out["rights"] = "us_and_china"
        elif "US RIGHTS" in up:
            out["rights"] = "us"
        elif re.search(r"PATENT|APPLICATION|PCT", up) and re.search(r"\d", line):
            # a label with no number ("PCT PATENT APPLICATION:") just introduces the next line
            out["ip_refs"].append(parse_ip_label(line))

    # Google Patents links in the header box, top to bottom
    links = sorted(
        [h for h in (page.hyperlinks or [])
         if "patents.google.com" in (h.get("uri") or "") and h["x0"] < 185 and h["top"] < 92],
        key=lambda h: h["top"])
    pubs = []
    for h in links:
        url = h["uri"].strip()
        m = re.search(r"/patent/([A-Z]{2}\d+[A-Z]\d?)", url)
        pubs.append((m.group(1) if m else None, url))

    # Pair links with IP lines by order only when counts match
    if pubs and len(pubs) == len(out["ip_refs"]):
        for ref, (pub, url) in zip(out["ip_refs"], pubs):
            ref["publication_number"], ref["google_patents_url"] = pub, url
            if pub and ref["ip_type"] == "granted_patent" and not re.search(r"B\d?$", pub):
                ref["flags"].append("granted_label_but_link_is_publication")
            if pub and ref["ip_type"] == "application" and re.search(r"B\d?$", pub):
                ref["flags"].append("application_label_but_link_is_grant")
    elif pubs:
        out["flags"].append("google_patents_links_not_paired")
        for pub, url in pubs:
            out["ip_refs"].append({"raw_label": None, "ip_type": "unknown", "country": pub[:2] if pub else None,
                                   "number_normalized": None, "publication_number": pub,
                                   "google_patents_url": url, "flags": ["from_link_only"]})

    if not out["ip_refs"]:
        out["flags"].append("no_ip_identifier_on_page")
    return out


# ---------- title ----------

def parse_title(page):
    box = crop(page, (185, 0, None, 92))
    return clean(flow_text(box)) or None


# ---------- people ----------

def split_person(chunk, role):
    chunk = clean(chunk)
    parts = [p.strip() for p in chunk.split(",")]
    name_raw = parts[0]
    rest = parts[1:]
    degrees = []
    while rest and rest[0].upper().replace(" ", "") in DEGREES:
        degrees.append(rest.pop(0))
    name = re.sub(r"^(Dr\.?|Prof\.?)\s+", "", name_raw).strip()
    return {"name": name, "name_raw": name_raw, "role": role,
            "degrees": degrees, "title_affiliation": ", ".join(rest).rstrip(")").strip() or None,
            "profile_url": None}


def parse_people(page):
    band = crop(page, PEOPLE_BAND)
    text = flow_text(band)
    text = re.sub(r"VIEW PUBLICATIONS?", "", text)
    people, role, prev_line = [], None, ""
    label_re = re.compile(r"(PRINCIPAL INVESTIGATORS?|CO-INVENTORS?|GRADUATE STUDENTS)\s*:")
    for line in text.splitlines():
        line = clean(line)
        if not line:
            continue
        pieces = label_re.split(line)
        # pieces: [before, LABEL, after, LABEL, after...]
        if pieces[0].strip() and role:                 # continuation line
            chunks = pieces[0].split("|")
            if people and re.search(r"(\band|,)$", prev_line):
                # wrapped title, e.g. "... (CPHAI) and" / "Professor in the Departments ..."
                first = clean(chunks.pop(0))
                p = people[-1]
                p["title_affiliation"] = clean(f"{p['title_affiliation'] or ''} {first}")
            for chunk in chunks:
                if chunk.strip():
                    people.append(split_person(chunk, role))
        for i in range(1, len(pieces), 2):
            role = ROLE_LABELS.get(pieces[i].upper(), "other")
            for chunk in pieces[i + 1].split("|"):
                if chunk.strip():
                    people.append(split_person(chunk, role))
        prev_line = line

    # Profile links: read the text under each link and match it to a person
    for h in page.hyperlinks or []:
        uri = (h.get("uri") or "").strip()
        if not uri.startswith("http") or not (88 <= h["top"] <= 126) or h["x0"] > 860:
            continue
        try:
            anchor = clean(flow_text(page.crop((h["x0"], h["top"], h["x1"], h["bottom"]))))
            anchor = re.sub(r"[^\w\s.\-’']", "", anchor).strip()
        except ValueError:
            continue
        for p in people:
            tokens = [t for t in anchor.split() if len(t) > 2 and t.upper() not in DEGREES]
            if tokens and p["profile_url"] is None and all(t in p["name_raw"] for t in tokens):
                p["profile_url"] = uri
                break
    return people


# ---------- sections (description, advantages, ...) ----------

def heading_of(line):
    key = re.sub(r"^VIEW PUBLICATIONS?\s*", "", line).rstrip(":").strip().upper()
    return SECTION_HEADINGS.get(key), key


def parse_sections(page):
    lines = [clean(l) for l in flow_text(page).splitlines()]
    sections, current = {}, None
    for line in lines:
        if not line:
            continue
        field, key = heading_of(line)
        if field:
            current = field
            sections.setdefault(current, [])
            continue
        if any(re.search(p, line) for p in STOP_PATTERNS):
            current = None
            continue
        if current:
            sections[current].append(line)

    def to_items(raw_lines):
        """Join wrapped lines; a bullet (•, h, ➤) starts a new item."""
        items = []
        for l in raw_lines:
            if re.match(r"^[•➤h]\s", l):
                items.append(re.sub(r"^[•➤h]\s", "", l))
            elif items:
                items[-1] += " " + l
            else:
                items.append(l)
        return [clean(i) for i in items]

    return {k: to_items(v) for k, v in sections.items()}


# ---------- contacts and publications ----------

def parse_contacts(page):
    text = flow_text(crop(page, CONTACT_BAND))
    pairs = re.findall(r"([A-Z][A-Za-z.\- ]+?)\s*\|\s*(\(\d{3}\)\s*\d{3}-\d{4})", text)
    role_lines = [clean(l) for l in text.splitlines()
                  if l.strip() and "|" not in l and not l.strip().startswith("CONTACT")]
    roles = []
    for l in role_lines:  # two roles can share one line when contacts sit side by side
        roles += re.findall(r"((?:Sr\.|Associate|Director)[^A-Z]*(?:[A-Z][a-z]+[^A-Z]*)*)", l) or [l]
    emails = [re.sub(r"%40", "@", re.search(r"mailto:([^?%]+(?:%40)[^?%]+)", h["uri"]).group(1))
              for h in sorted(page.hyperlinks or [], key=lambda h: h["x0"])
              if (h.get("uri") or "").startswith("mailto:") and re.search(r"mailto:([^?%]+(?:%40)[^?%]+)", h["uri"])]
    contacts, seen = [], set()
    for i, (name, phone) in enumerate(pairs):
        name = clean(re.sub(r"^CONTACTS?:\s*", "", name))
        if name in seen:                     # same contact printed twice on a page
            continue
        seen.add(name)
        last = name.split()[-1].lower()
        email = next((e for e in emails if last in e.lower()), None)   # pair by last name, not by order
        contacts.append({"name": name, "phone": phone,
                         "role": clean(roles[i]) if i < len(roles) else None,
                         "email": email})
    return contacts


def parse_publications(page):
    pubs, seen = [], set()
    for h in page.hyperlinks or []:
        uri = (h.get("uri") or "").strip()
        if not uri.startswith("http") or "patents.google.com" in uri:
            continue
        if 88 <= h["top"] <= 126 and h["x0"] < 860:      # people profile links
            continue
        if uri in seen:
            continue
        seen.add(uri)
        doi = re.search(r"(10\.\d{4,9}/[^\s?#]+)", uri)
        pmid = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", uri)
        pubs.append({"url": uri, "doi": doi.group(1).rstrip("/") if doi else None,
                     "pmid": pmid.group(1) if pmid else None})
    return pubs


# ---------- one page -> one Technology record ----------

def parse_page(page, page_no, document, category, extracted_at):
    header = parse_header(page)
    if not header["tto_id"]:
        return None                      # cover page or non-technology page
    sections = parse_sections(page)
    record = {
        "schema_version": "0.1",
        "tto_id": header["tto_id"],
        "title": parse_title(page),
        "category": category,
        "status": header["status"],
        "rights": header["rights"],
        "description": " ".join(sections.pop("description", [])) or None,
        "advantages": sections.pop("advantages", []),
        "other_sections": sections,
        "ip_refs": header["ip_refs"],
        "people": parse_people(page),
        "contacts": parse_contacts(page),
        "publications": parse_publications(page),
        "source": {"system": "dartmouth_tto", "document": document, "page": page_no,
                   "source_url": SOURCE_URL, "extracted_at": extracted_at,
                   "extractor_version": EXTRACTOR_VERSION},
        "quality_flags": header["flags"],
    }
    if not record["description"]:
        record["quality_flags"].append("description_not_found")
    if not any(p["role"] == "principal_investigator" for p in record["people"]):
        record["quality_flags"].append("no_principal_investigator_found")
    for ref in record["ip_refs"]:
        record["quality_flags"] += [f"ip:{f}" for f in ref["flags"]]
    return record


SHARED_FLAGS = ("publication_number_shared:", "ip_number_shared:")


def flag_cross_record_issues(records):
    """The same publication or IP number on two technologies is probably a copy-paste
    error on one of the pages. Safe to rerun: old cross-record flags are replaced."""
    pubs, numbers = {}, {}
    for r in records:
        r["quality_flags"] = [f for f in r["quality_flags"] if not f.startswith(SHARED_FLAGS)]
        for ref in r["ip_refs"]:
            if ref["publication_number"]:
                pubs.setdefault(ref["publication_number"], []).append(r["tto_id"])
            if ref["number_normalized"]:
                numbers.setdefault(ref["number_normalized"], []).append(r["tto_id"])
    for prefix, owners in (("publication_number_shared", pubs), ("ip_number_shared", numbers)):
        for value, ids in owners.items():
            ids = sorted(set(ids))
            if len(ids) > 1:
                for r in records:
                    if r["tto_id"] in ids:
                        r["quality_flags"].append(f"{prefix}:{value}:{','.join(ids)}")


def merge_duplicates(records):
    """A technology printed on several pages (or in several decks) becomes one record:
    the first page wins, IP references are combined, and each extra page is noted."""
    merged = {}
    for r in records:
        first = merged.get(r["tto_id"])
        if first is None:
            merged[r["tto_id"]] = r
            continue
        if r["category"] and r["category"] not in (first["category"] or "").split(" / "):
            first["category"] = f"{first['category']} / {r['category']}" if first["category"] else r["category"]
        seen = {(x["ip_type"], x["number_normalized"] or x["raw_label"]) for x in first["ip_refs"]}
        for ref in r["ip_refs"]:
            if (ref["ip_type"], ref["number_normalized"] or ref["raw_label"]) not in seen:
                first["ip_refs"].append(ref)
                first["quality_flags"] += [f"ip:{f}" for f in ref["flags"]]
        first["rights"] = first["rights"] or r["rights"]
        first["quality_flags"].append(f"also_listed:{r['source']['document']}:p{r['source']['page']}")
    for r in merged.values():
        if r["ip_refs"]:
            r["quality_flags"] = [f for f in r["quality_flags"] if f != "no_ip_identifier_on_page"]
    return list(merged.values())


def crawl(pdf_path, category):
    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    document = pdf_path.split("/")[-1]
    records = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            rec = parse_page(page, i, document, category, extracted_at)
            if rec:
                records.append(rec)
    flag_cross_record_issues(records)
    return records


def category_from_file(pdf_path):
    """'data/raw/Physical-Sciences.pdf' -> 'Physical Sciences'."""
    return pdf_path.split("/")[-1].rsplit(".", 1)[0].replace("-", " ").replace("_", " ")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="+")
    ap.add_argument("--category", default=None, help="only with one PDF; default: from the file name")
    ap.add_argument("-o", "--output", default="technologies.json")
    args = ap.parse_args()
    if args.category and len(args.pdf) > 1:
        ap.error("--category works with one PDF; with several, each category comes from its file name")
    recs = []
    for pdf in args.pdf:
        recs += crawl(pdf, args.category or category_from_file(pdf))
    recs = merge_duplicates(recs)
    flag_cross_record_issues(recs)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(recs, f, indent=2, ensure_ascii=False)
    flagged = sum(1 for r in recs if r["quality_flags"])
    print(f"{len(recs)} technologies written to {args.output} ({flagged} with quality flags)")
