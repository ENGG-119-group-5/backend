# How the backend works (plain-language guide)

This page explains what the backend does and how its parts fit together, in everyday words. You don't need to know how to code to follow it. For exact formats and commands, see the [README](../README.md) and [data_contract.md](data_contract.md).

## The big picture

The tool helps a venture capital (VC) team answer one question quickly: **"Which of Dartmouth's inventions fit what we want to invest in?"**

To answer it, the backend does three jobs:

1. **Collects the facts.** It reads Dartmouth's tech-transfer brochures and looks up the official patent records behind them.
2. **Stores them in a connected way.** It puts everything in a database that remembers how inventions, patents and people are related.
3. **Answers questions from the website.** It serves search results and invention details, and it uses Claude (an AI model) to compare an investor's thesis against every invention.

```text
 TTO brochure PDFs ──► 1. read the pages ──┐
                                            ├─► 3. link them ──► 4. load into Neo4j ──► API ──► website
 Patent numbers ────► 2. fetch USPTO data ─┘                                            │
                                                                     Claude (matching) ◄┘
```

## Words you will see

| Word | Meaning |
| --- | --- |
| **TTO** | Dartmouth's Technology Transfer Office. It publishes the inventions that companies can license. |
| **Technology / invention** | One item from the TTO brochures, such as a new drug delivery method. |
| **USPTO** | The US Patent and Trademark Office, the official source of patent facts. |
| **Patent / application** | A *granted patent* is approved protection. An *application* has been filed but not approved yet. |
| **Thesis** | A short document from an investor saying what they want to fund (sectors, problems, stage, deal type). |
| **Neo4j** | The database we use. It stores things as dots and their relationships as arrows (a "graph"). |
| **API** | The set of web addresses the website calls to get data, such as `/search`. |
| **Claude** | The AI model from Anthropic that reads a thesis and grades each invention against it. |

## Part 1: The data pipeline (getting the facts in)

These four scripts run in order. The `scripts/load_demo.sh` script runs steps 3 and 4 for the demo data, which is already prepared.

### Step 1: Read the brochures (`src/tto_crawler.py`)
The TTO brochures are PDFs with one invention per page. This script reads each page and pulls out the title, the case number (such as `2021-023`), the patent numbers, the inventors, the description and the advantages. It saves each invention as a tidy record.

It **never guesses**. If something on a page is unclear, or two pages share the same patent number (a likely copy-paste error), it adds a *quality flag* so a person can check. If an invention appears twice, the two copies are merged into one.

### Step 2: Look up the official patents (`src/fetch_patents.py`)
The brochures only print patent *numbers*. This script looks each one up on Google Patents, which mirrors the official USPTO records, and saves the facts: title, abstract, dates, inventors, owners, and whether the US government helped fund the research. Downloaded pages are kept on disk, so running it again is instant.

### Step 3: Connect inventions to patents (`src/link_v1.py`)
This script decides which patent belongs to which invention, **using exact numbers only**:

- When the patent or application number matches exactly, the link is **confirmed** (confidence 1.0).
- When only the publication number matches and the other numbers disagree, the link is **uncertain** (confidence 0.5). It is kept aside for a person to review and never shown as fact.

### Step 4: Load the database (`src/load_to_neo4j.py`)
This script writes everything into Neo4j as a graph:

```text
(Inventor) ──LISTED_ON──► (Technology) ──PROTECTED_BY──► (Patent) ──ASSIGNED_TO──► (Assignee)
(Inventor) ──INVENTED───────────────────────────────────►(Patent)
```

It is safe to run twice, because it updates existing records instead of making copies.

**Helpers:** `src/normalize.py` makes sure a number or name is always written the same way, so that `US 10,123,456` and `10123456` are recognised as the same patent. `src/config.py` and `src/db.py` hold the database settings and connection.

## Part 2: The API (answering the website)

The API lives in `src/api/main.py`. It runs as a small web server on port 8000, and the website calls it. The website never talks to the database directly.

| Address | What it does |
| --- | --- |
| `GET /search?q=...` | Keyword search across inventions, patents and inventors. Every word you type must appear in a result. Results with all the words in the title come first. |
| `GET /technology/{id}` | Everything about one invention: summary, linked patents, inventors, its IP score with the full breakdown, and its change history. |
| `GET /samples` | The two sample investment theses offered on the home page. |
| `POST /match` | Upload a thesis PDF and get every invention back, labelled and ranked. |

`src/api/models.py` defines the exact shape of each answer, so the website always gets data it can read.

### The IP score (`src/api/scoring.py`)
Every invention gets a 0–100 **IP-potential score**: a quick measure of how strong its patent position is. **No AI is involved.** It adds up six simple checks, each worth a fixed share of the 100 points:

| Check | Points | Full points when… |
| --- | --- | --- |
| Patent protection | 30 | there is a granted patent (an application earns 15) |
| Link confidence | 15 | the patent link is certain |
| Linked patents | 15 | there are 3 or more confirmed patents |
| Federal funding | 15 | a patent says the government funded the research |
| Recent activity | 15 | the newest patent date is this year (older dates earn less) |
| Availability | 10 | the TTO lists it as available to license |

The website shows every check with its reason, so anyone can see why an invention got its score. An analyst can override the number with a written reason, and the original score is still kept.

### Thesis matching (`src/api/matcher.py`)
This is the AI part, and it runs when someone uploads a thesis:

1. The API writes a plain-text summary of every invention: its TTO description plus its official patent facts.
2. It sends Claude the thesis PDF and all those summaries in one request.
3. Claude grades each invention on four questions, each from 0 (no) to 2 (clearly yes):
   - **Area:** is it in a field the thesis targets?
   - **Problem:** does it solve a problem the thesis cares about?
   - **Stage:** is it mature enough for this investor?
   - **Deal:** do its patent status and the TTO's terms allow the deal the investor wants?
4. For each grade, Claude must **copy a short quote** from the invention's record as proof.
5. **Our own code checks every quote.** If a quote doesn't appear word for word in the record, the website marks it with a warning. This catches made-up evidence.
6. Each invention is labelled **Strong**, **Potential** or **No relevance** and sorted: strong first, then by total grade, then by IP score.

If Claude skips an invention in a long list, the API asks again for just the missing ones.

**Sample theses cost nothing.** The results for the two sample PDFs were saved once (by `scripts/run_demo_matches.py`) in `data/demo/results/`. The API recognises those PDFs by their fingerprint and returns the saved answer instantly, with no API key and no cost. Only a *new* PDF calls Claude, and that needs an `ANTHROPIC_API_KEY` in `.env.local`.

## Part 3: Running it

- **One click (macOS):** double-click `Start Demo.command`. It starts the database, loads the demo data, starts the API and the website, and opens your browser. See the README for first-time setup.
- **By hand:** follow the README sections *Setup*, *Start Neo4j*, *Demo dataset* and *Run the API*.
- **Tests:** `pytest` checks the crawler, linking, scoring, matcher and API. They also run automatically on GitHub for every change.

## Where things are

| Folder | What's inside |
| --- | --- |
| `src/` | The pipeline scripts (steps 1–4) and helpers |
| `src/api/` | The web API, the IP score and the thesis matcher |
| `data/demo/` | The demo dataset: 41 real Dartmouth inventions, their real USPTO records, the sample theses and their saved results |
| `scripts/` | `load_demo.sh` (load the demo data) and `run_demo_matches.py` (refresh the saved sample results) |
| `tests/` | Automated checks |
| `docs/` | This guide and the data contract |
