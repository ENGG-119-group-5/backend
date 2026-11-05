# Data Contract — VC Due Diligence Tool (Group 5)

**Version:** 0.2 · **Owner:** Augustin · **Status:** draft for review by Prajwal (TTO) and Mia (USPTO)

> **Why this document exists:** everyone writes data in the same format, so the TTO crawler, the USPTO loader, the linking step and the API can be built in parallel. If you need a new field, add it here first, then in code.

---

## 1. General rules

- Format: **JSON**, UTF-8, one list of records per file.
- Every record has a `source` block (where it comes from, when, which script). This is what makes citations possible later.
- **Never guess.** If a value is unclear, keep the raw text and add a `quality_flags` entry.
- Field names are `snake_case`. Missing values are `null`, missing lists are `[]`.
- Every file has a `schema_version`. Current: `"0.1"`.

---

## 2. Technology record (source: Dartmouth TTO)

Produced by `tto_crawler.py`. One record per technology page.

| Field | Type | Example | Notes |
| --- | --- | --- | --- |
| `schema_version` | string | `"0.1"` | |
| `tto_id` | string | `"2018-168"` | **Primary key.** Dartmouth case number |
| `title` | string | `"Non-Invasive Dielectric Probe…"` | |
| `category` | string | `"Life Sciences"` | Name of the TTO PDF it comes from |
| `status` | enum | `available_for_license` / `portfolio_available_for_review` | |
| `rights` | enum or null | `worldwide` / `us` / `null` | |
| `description` | string | | Text of DESCRIPTION / INVENTION OVERVIEW |
| `advantages` | list of strings | | One item per bullet |
| `other_sections` | object | `{"looking_for": [...]}` | `features`, `efficacy`, `looking_for` |
| `ip_refs` | list of IpRef | | See 2.1 |
| `people` | list of Person | | See 2.2 |
| `contacts` | list of Contact | | TTO licensing managers |
| `publications` | list of Publication | | From "View publication" links |
| `source` | Source | | See section 4 |
| `quality_flags` | list of strings | `["no_ip_identifier_on_page"]` | |

### 2.1 IpRef

| Field | Type | Example | Notes |
| --- | --- | --- | --- |
| `raw_label` | string | `"US PATENT APPLICATION 17/264,691"` | Exactly as printed |
| `ip_type` | enum | `granted_patent`, `application`, `pct`, `provisional`, `unknown` | Decided from the **number format**, not only the label |
| `country` | string | `"US"`, `"WO"` | |
| `number_normalized` | string | `"17264691"`, `"10113979"`, `"PCT/US2021/014145"` | Digits only for US numbers |
| `publication_number` | string or null | `"US20240000316A1"` | From the Google Patents link on the page |
| `google_patents_url` | string or null | | |
| `flags` | list | `["label_says_patent_but_number_is_application"]` | |

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

- **Contact:** `name`, `phone`, `role`, `email`
- **Publication:** `url`, `doi` (if found in the URL), `pmid` (if PubMed link)

---

## 3. Patent record (source: USPTO) — for Mia

Proposal: one record per patent document (grant **or** published application).

| Field | Type | Example | Notes |
| --- | --- | --- | --- |
| `schema_version` | string | `"0.1"` | |
| `patent_key` | string | `"US-10113979"` or `"US-APP-17264691"` | **Primary key**, see 5.1 |
| `doc_type` | enum | `grant`, `application` | |
| `patent_number` | string or null | `"10113979"` | Grants only |
| `application_number` | string or null | `"17264691"` | Digits only |
| `publication_number` | string or null | `"US20240000316A1"` | |
| `title` | string | | |
| `abstract` | string | | Used for embeddings and RAG |
| `filing_date` | date | `"2021-01-29"` | ISO format |
| `grant_date` | date or null | | |
| `inventors` | list | `[{"first": "Paul", "last": "Meaney", "city": "Hanover", "state": "NH", "country": "US"}]` | Keep first and last separate |
| `assignees` | list | `[{"name": "Trustees of Dartmouth College"}]` | |
| `government_interest` | string or null | `"This invention was made with government support under grant ..."` | **Our funding signal** |
| `source` | Source | | |
| `quality_flags` | list | | |

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

For USPTO: `"system": "uspto"`, plus the API endpoint and the cached response file name.

---

## 5. Keys and normalization

### 5.1 Patent keys

| Case | Key format | Example |
| --- | --- | --- |
| Granted US patent | `US-<number>` | `US-10113979` |
| US application | `US-APP-<series+number>` | `US-APP-17264691` |
| PCT application | `WO-<PCT number>` | `WO-PCT/US2021/014145` |
| Provisional | `US-PROV-<number>` | `US-PROV-63744007` (not public, no USPTO record) |

Rule: remove commas, slashes and spaces from US numbers. `17/264,691` → `17264691`.

### 5.2 Names

Keep `name_raw` always. For matching, use a `name_key`: lowercase, no titles (Dr., Prof.), no degrees, no punctuation, first name + last name. Middle initials are kept separately, not in the key.

---

## 6. Neo4j schema (milestone 2)

### Nodes

| Label | Key property | Main properties |
| --- | --- | --- |
| `Technology` | `tto_id` | `title`, `status`, `rights`, `category`, `description` |
| `Patent` | `patent_key` | `doc_type`, `title`, `abstract`, `filing_date`, `grant_date`, `government_interest` |
| `Inventor` | `inventor_id` | `name`, `name_key`, `source` (`tto` / `uspto`) |
| `Assignee` | `name_normalized` | `name` |
| `IpRef` | `ref_key` (`<tto_id>#<n>`) | What the TTO page **claims**: `raw_label`, `ip_type`, `patent_key`, `publication_number`, `flags` |

> **Notes:** `IpRef` keeps the TTO claim separate from the USPTO fact (`Patent`). The link between them is decided by the linking step, never assumed.

### Relationships

| Relationship | Properties | Created by |
| --- | --- | --- |
| `(Technology)-[:CLAIMS_IP]->(IpRef)` | | TTO loader |
| `(Inventor)-[:LISTED_ON {role}]->(Technology)` | `role` | TTO loader |
| `(Inventor)-[:INVENTED]->(Patent)` | | USPTO loader |
| `(Patent)-[:ASSIGNED_TO]->(Assignee)` | | USPTO loader |
| `(Technology)-[:PROTECTED_BY]->(Patent)` | `match_method`, `confidence`, `evidence_ref`, `matched_at` | **Linking step**, confirmed links only |
| `(Technology)-[:POSSIBLY_PROTECTED_BY]->(Patent)` | `match_method`, `confidence`, `conflicts`, `review_status` | **Linking step**, uncertain links, waiting for human review |
| `(Inventor)-[:SAME_AS]->(Inventor)` | `match_method`, `confidence`, `status` (`confirmed` / `uncertain`) | Entity resolution, v2 |

`match_method` values: `patent_number`, `application_number`, `publication_number`, `title_inventor` (v2), `human_review`.

### Constraints (run once)

```cypher
CREATE CONSTRAINT technology_id IF NOT EXISTS FOR (t:Technology) REQUIRE t.tto_id IS UNIQUE;
CREATE CONSTRAINT patent_key IF NOT EXISTS FOR (p:Patent) REQUIRE p.patent_key IS UNIQUE;
CREATE CONSTRAINT ipref_key IF NOT EXISTS FOR (r:IpRef) REQUIRE r.ref_key IS UNIQUE;
CREATE CONSTRAINT inventor_id IF NOT EXISTS FOR (i:Inventor) REQUIRE i.inventor_id IS UNIQUE;
CREATE CONSTRAINT assignee_name IF NOT EXISTS FOR (a:Assignee) REQUIRE a.name_normalized IS UNIQUE;
```

Loaders use `MERGE` on these keys, so they are **rerunnable** (running twice does not create duplicates).

---

## 7. What the first PDF taught us (Life Sciences, 29 technologies)

> **Notes:** these findings change how linking v1 can work. They are also good material for Status Update #2 (honest evaluation).

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

---

## 8. Open questions for the team

- [ ] **Mia:** can the USPTO loader include published applications (not only grants)? This doubles our link coverage.
- [ ] **Mia:** can you return `government_interest` text? It is our only funding signal in the MVP.
- [ ] **Prajwal:** do you take the crawler from here for the other TTO PDFs (other categories)? Target date: ____
- [ ] **All:** OK with `Inventor` as the single label for people from both sources, linked with `SAME_AS`?
