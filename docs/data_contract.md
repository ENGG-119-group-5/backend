# Data Contract

**Version:** 0.3 · **Owner:** Augustin · **Status:** shared with Prajwal (TTO) and Mia (USPTO) on Nov 5, waiting for answers (section 9)

> **Why this document exists:** everyone writes data in the same format, so the TTO crawler, the USPTO loader, the linking step and the API can be built in parallel. If you need a new field, add it here first, then in code.

**Changes in v0.3:** `patent_key` is computed, not provided · inventor ID formats documented · `match_method` is a list · name-key rule corrected · new Link record (section 6) · file locations (section 8).

---

## 1. General rules

- Format: **JSON**, UTF-8. Record files contain one list of records. Exception: `links.json` (section 6).
- Every record has a `source` block (where it comes from, when, which script). This is what makes citations possible later.
- **Never guess.** If a value is unclear, keep the raw text and add a `quality_flags` entry.
- Field names are `snake_case`. Missing values are `null`, missing lists are `[]`.
- Every record has a `schema_version`. Current record schema: `"0.1"` (the document version above is separate).

---

## 2. Technology record (source: Dartmouth TTO)

Produced by `src/tto_crawler.py`. One record per technology page.

| Field | Type | Example | Notes |
| --- | --- | --- | --- |
| `schema_version` | string | `"0.1"` | |
| `tto_id` | string | `"2018-168"` | **Primary key.** Dartmouth case number |
| `title` | string | `"Non-Invasive Dielectric Probe…"` | |
| `category` | string | `"Life Sciences"` | Name of the TTO PDF it comes from |
| `status` | enum | `available_for_license` / `portfolio_available_for_review` | |
| `rights` | enum or null | `worldwide` / `us` / `null` | |
| `description` | string or null | | Text of DESCRIPTION / INVENTION OVERVIEW |
| `advantages` | list of strings | | One item per bullet |
| `other_sections` | object | `{"looking_for": [...]}` | Keys: `features`, `efficacy`, `looking_for` |
| `ip_refs` | list of IpRef | | See 2.1 |
| `people` | list of Person | | See 2.2 |
| `contacts` | list of Contact | | TTO licensing managers, no duplicates |
| `publications` | list of Publication | | From "View publication" links |
| `source` | Source | | See section 4 |
| `quality_flags` | list of strings | `["no_ip_identifier_on_page"]` | Includes IpRef flags as `ip:<flag>` |

### 2.1 IpRef

| Field | Type | Example | Notes |
| --- | --- | --- | --- |
| `raw_label` | string or null | `"US PATENT APPLICATION 17/264,691"` | Exactly as printed. `null` if the ref comes from a link only |
| `ip_type` | enum | `granted_patent`, `application`, `pct`, `provisional`, `unknown` | Decided from the **number format**, not only the label |
| `country` | string or null | `"US"`, `"WO"` | |
| `number_normalized` | string or null | `"17264691"`, `"10113979"`, `"PCT/US2021/014145"` | Digits only for US numbers |
| `publication_number` | string or null | `"US20240000316A1"` | From the Google Patents link on the page |
| `google_patents_url` | string or null | | |
| `flags` | list | `["label_says_patent_but_number_is_application"]` | |

Possible IpRef flags: `label_says_patent_but_number_is_application`, `label_says_application_but_number_is_provisional`, `application_number_missing_slash`, `granted_label_but_link_is_publication`, `application_label_but_link_is_grant`, `from_link_only`.

### 2.2 Person (from TTO)

| Field | Type | Example |
| --- | --- | --- |
| `name` | string | `"Randolph J. Noelle"` (no "Dr.") |
| `name_raw` | string | `"Dr. Randolph J. Noelle"` |
| `role` | enum | `principal_investigator`, `co_inventor`, `graduate_student` |
| `degrees` | list | `["MD", "PhD"]` |
| `title_affiliation` | string or null | `"Emeritus Professor of Microbiology & Immunology"` |
| `profile_url` | string or null | Faculty page link |

### 2.3 Contact and Publication

- **Contact:** `name`, `phone`, `role`, `email` (email paired by last name)
- **Publication:** `url`, `doi` (if found in the URL), `pmid` (if PubMed link)

---

## 3. Patent record (source: USPTO) - for Mia

One record per patent document (grant **or** published application). Loaded by `src/load_to_neo4j.py patents`.

| Field | Type | Example | Notes |
| --- | --- | --- | --- |
| `schema_version` | string | `"0.1"` | |
| `doc_type` | enum | `grant`, `application` | |
| `patent_number` | string or null | `"10113979"` | Grants only. **Required for grants** |
| `application_number` | string or null | `"17264691"` | Digits only. **Required for applications** |
| `publication_number` | string or null | `"US20240000316A1"` | Strongly recommended: used by linking |
| `title` | string | | |
| `abstract` | string | | Used for embeddings and RAG |
| `filing_date` | date or null | `"2021-01-29"` | ISO format |
| `grant_date` | date or null | | |
| `inventors` | list | `[{"first": "Paul", "last": "Meaney", "city": "Hanover", "state": "NH", "country": "US"}]` | Keep first and last separate |
| `assignees` | list | `[{"name": "Trustees of Dartmouth College"}]` | |
| `government_interest` | string or null | `"This invention was made with government support under grant ..."` | **Our funding signal** |
| `source` | Source | | |
| `quality_flags` | list | | Test data uses `["test_fixture"]` |

> **Notes:** do **not** provide `patent_key`. The loader computes it from `patent_number` / `application_number` (section 5.1), so the rule lives in one place (`src/normalize.py`). A record with neither number is skipped.

---

## 4. Source block (all records)

```json
"source": {
  "system": "dartmouth_tto",
  "document": "Life-Sciences.pdf",
  "page": 6,
  "source_url": "https://tto.dartmouth.edu/engage-us/licensing-opportunities",
  "extracted_at": "2026-10-27T14:00:00+00:00",
  "extractor_version": "tto_crawler/0.1"
}
```

`system` values: `dartmouth_tto`, `uspto` (plus the API endpoint and the cached response file name), `test_fixture`.

---

## 5. Keys and normalization

All rules are implemented in `src/normalize.py`. Use these functions, never rebuild keys by hand.

### 5.1 Patent keys

| Case | Key format | Example |
| --- | --- | --- |
| Granted US patent | `US-<number>` | `US-10113979` |
| US application | `US-APP-<series+number>` | `US-APP-17264691` |
| PCT application | `WO-<PCT number>` | `WO-PCT/US2021/014145` |
| Provisional | `US-PROV-<number>` | `US-PROV-63744007` (not public, no USPTO record) |

- Remove commas, slashes and spaces from US numbers: `17/264,691` → `17264691`.
- One key per document. If a grant record also has an application number, the **grant key wins**; linking still finds it by application number.

### 5.2 Names

Keep `name_raw` always. For matching, `name_key` is: lowercase, accents removed, apostrophes removed, titles (Dr., Prof.) and degrees (MD, PhD, MPH…) removed, **middle initials dropped**, then first token + last token.

| Name | `name_key` |
| --- | --- |
| `Dr. Randolph J. Noelle` | `randolph noelle` |
| `George A. O’Toole` | `george otoole` |
| `Lucas Salas, MD, PhD` | `lucas salas` |

Known limit: nicknames are not merged (`randy noelle` ≠ `randolph noelle`). That is the job of `SAME_AS` in v2.

### 5.3 Other IDs

| Node | ID format | Example |
| --- | --- | --- |
| Inventor from TTO | `tto:<name_key>` | `tto:paul meaney` |
| Inventor from USPTO | `uspto:<name_key>\|<city lowercase>` | `uspto:paul meaney\|hanover` |
| IpRef | `<tto_id>#<n>` (n = line order on the page, from 0) | `2018-168#1` |
| Assignee | lowercase name, single spaces | `trustees of dartmouth college` |

---

## 6. Link record (output of linking)

Produced by `src/link_v1.py`. The file is an object, not a list:

```json
{
  "report": {
    "technologies": 29, "patents": 4, "refs_total": 29,
    "refs_not_in_uspto": 12, "refs_without_number": 0, "refs_searchable_not_found": 13,
    "links_confirmed": 3, "links_uncertain": 1, "technologies_with_confirmed_link": 2
  },
  "links": [ { "...": "one Link per (tto_id, patent_key)" } ]
}
```

| Field | Type | Example | Notes |
| --- | --- | --- | --- |
| `tto_id` | string | `"2018-168"` | |
| `patent_key` | string | `"US-APP-17264691"` | |
| `methods` | list | `["application_number", "publication_number"]` | All identifiers that agreed |
| `confidence` | float | `1.0` | 1.0 = patent or application number · 0.9 = publication number only · 0.5 = uncertain |
| `status` | enum | `confirmed` / `uncertain` | |
| `conflicts` | list | `["page says application 18229086, patent record says 17264691"]` | Why it is uncertain |
| `flags` | list | `["patent_also_confirmed_on:2021-026"]` | |
| `evidence_ref` | string | `"2018-168#1"` | The IpRef behind the link |
| `source_page` | int | `6` | Page of the TTO PDF |
| `matched_at` | datetime | | |
| `linker_version` | string | `"link_v1/0.1"` | |

---

## 7. Neo4j schema (milestone 2)

### Nodes

| Label | Key property | Main properties |
| --- | --- | --- |
| `Technology` | `tto_id` | `title`, `category`, `status`, `rights`, `description`, `advantages`, `source_document`, `source_page`, `extracted_at`, `quality_flags` |
| `IpRef` | `ref_key` | What the TTO page **claims**: `raw_label`, `ip_type`, `patent_key`, `number_normalized`, `publication_number`, `google_patents_url`, `flags` |
| `Patent` | `patent_key` | `doc_type`, `patent_number`, `application_number`, `publication_number`, `title`, `abstract`, `filing_date`, `grant_date`, `government_interest`, `source_system`, `quality_flags` |
| `Inventor` | `inventor_id` | `name`, `name_key`, `source` (`tto` / `uspto`), `profile_url` (TTO), `city`, `state`, `country` (USPTO) |
| `Assignee` | `name_normalized` | `name` |

> **Notes:** `IpRef` keeps the TTO claim separate from the USPTO fact (`Patent`). The link between them is decided by the linking step, never assumed.

### Relationships

| Relationship | Properties | Created by |
| --- | --- | --- |
| `(Technology)-[:CLAIMS_IP]->(IpRef)` | | TTO loader |
| `(Inventor)-[:LISTED_ON]->(Technology)` | `role`, `title_affiliation` | TTO loader |
| `(Inventor)-[:INVENTED]->(Patent)` | | USPTO loader |
| `(Patent)-[:ASSIGNED_TO]->(Assignee)` | | USPTO loader |
| `(Technology)-[:PROTECTED_BY]->(Patent)` | `match_method` (list), `confidence`, `evidence_ref`, `matched_at`, `linker_version`, `flags` | Linking, **confirmed links only** |
| `(Technology)-[:POSSIBLY_PROTECTED_BY]->(Patent)` | `match_method` (list), `confidence`, `conflicts`, `evidence_ref`, `matched_at`, `linker_version`, `review_status` | Linking, uncertain links waiting for human review |
| `(Inventor)-[:SAME_AS]->(Inventor)` | `match_method`, `confidence`, `status` | Entity resolution, **v2 (not built yet)** |

`match_method` values: `patent_number`, `application_number`, `publication_number`; later `title_inventor` (v2) and `human_review`.
`review_status` values: `pending` (default), then `accepted` / `rejected` after review.

### Constraints (run once: `python src/load_to_neo4j.py schema`)

```cypher
CREATE CONSTRAINT technology_id IF NOT EXISTS FOR (t:Technology) REQUIRE t.tto_id IS UNIQUE;
CREATE CONSTRAINT patent_key IF NOT EXISTS FOR (p:Patent) REQUIRE p.patent_key IS UNIQUE;
CREATE CONSTRAINT ipref_key IF NOT EXISTS FOR (r:IpRef) REQUIRE r.ref_key IS UNIQUE;
CREATE CONSTRAINT inventor_id IF NOT EXISTS FOR (i:Inventor) REQUIRE i.inventor_id IS UNIQUE;
CREATE CONSTRAINT assignee_name IF NOT EXISTS FOR (a:Assignee) REQUIRE a.name_normalized IS UNIQUE;
```

Loaders use `MERGE` on these keys, so they are **rerunnable** (running twice does not create duplicates).

---

## 8. File locations

| What | Where | In git? |
| --- | --- | --- |
| TTO PDFs | `data/raw/` | No |
| Cached USPTO responses | `data/cache/` | No |
| Crawler output, links | `data/processed/` | No (regenerate anytime) |
| Frozen test data | `tests/fixtures/` | Yes |

---

## 9. What the first PDF taught us (Life Sciences, 29 technologies)

| IP situation | Count | Can we link to USPTO by number? |
| --- | --- | --- |
| Granted US patent | 5 | Yes |
| US application only | 9 | Yes, **if Mia also loads applications**, not only grants |
| PCT only | 5 | No (WIPO, not USPTO) |
| Provisional only | 6 | No (provisional applications are not public) |
| No identifier ("extensive IP portfolio") | 4 | No |

So the **maximum** for number-based linking is about 14 of 29. The other 15 need inventor-name matching (v2) or stay unlinked, which is an honest result, not a bug.

Data quality issues found in the source PDF:

- **Wrong labels:** 2021-023 and 2022-019 say "US PATENT NO" but the number is an application number (18/…). 2025-021 says "APPLICATION" but 63/… is a provisional.
- **Missing slash:** 2018-119 prints `16,639,836` for application 16/639,836.
- **Copy-paste error:** 2018-168 and 2021-026 link to the same Google Patents publication (US20240000316A1), although they are different technologies.
- **Name variants:** "Dr. Randy Noelle" (2004-0269) vs "Dr. Randolph J. Noelle" (2024-005). This is exactly the entity-resolution problem the project must solve.
- **Possible typo:** "Jacqueline M. Andreozz" (2021-027), likely truncated.
- **Typo in heading:** "DESCRIPTON" (2024-029), handled by the crawler.
- **Extraction limit:** chart labels can leak into the text (e.g. "VISTA as a Ligand" in 2004-0269).

---

## 10. Open questions for the team

- [ ] **Mia:** can the USPTO loader include published applications (not only grants)? This raises our possible links from 5 to 14 technologies.
- [ ] **Mia:** can you return `government_interest` text? It is our only funding signal in the MVP.
- [ ] **Prajwal:** do you take the crawler for the other TTO PDFs (other categories)? Target date: **Tue Nov 10**
- [ ] **All:** OK with `Inventor` as the single label for people from both sources, linked with `SAME_AS`?
