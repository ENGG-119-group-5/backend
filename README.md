# VC Due Diligence Tool: backend

[![CI](https://github.com/ENGG-119-group-5/backend/actions/workflows/ci.yml/badge.svg)](https://github.com/ENGG-119-group-5/backend/actions/workflows/ci.yml)

Pipeline v0.1 (TTO → Neo4j → linking) and the FastAPI API used by the [web app](https://github.com/ENGG-119-group-5/webapp). Data formats follow [`docs/data_contract.md`](docs/data_contract.md) (v0.5).

## Files

| File | What it does |
| --- | --- |
| `src/tto_crawler.py` | Reads Dartmouth TTO licensing PDFs (one technology per page) into Technology records; merges repeats |
| `src/fetch_patents.py` | Fetches the real USPTO record for each US patent / application number on the TTO pages (public Google Patents pages, cached) |
| `src/normalize.py` | Shared rules for patent keys and name keys (one place, used by all scripts) |
| `src/load_to_neo4j.py` | Creates the schema, loads TTO technologies and USPTO patents. Rerunnable (`MERGE`) |
| `src/link_v1.py` | Links technologies to patents by exact identifiers. Writes `links.json`, optionally Neo4j |
| `src/config.py` | Neo4j settings, read from `.env` then `.env.local` |
| `src/api/` | FastAPI app (`main.py`), response models (`models.py`), rule-based IP score (`scoring.py`) |
| `tests/fixtures/technologies_life_sciences.json` | Frozen crawler output for the Life Sciences PDF (29 technologies) |
| `tests/fixtures/uspto_patents_test.json` | 4 **fake** patent records to test linking before the real USPTO data |
| `data/validation/spinout_cases.csv` | Known Dartmouth spin-outs with their expected patents and inventors |
| `data/demo/` | Demo dataset: 41 **real** Dartmouth TTO listings and the 20 **real** USPTO records they cite |
| `scripts/load_demo.sh` | Replaces the graph with the demo dataset |
| `src/api/matcher.py` | Thesis matcher: one Claude call scores every technology against a thesis PDF |
| `data/demo/theses/` | Two sample theses (PDF + Markdown source) |
| `data/demo/results/` | Saved real match results for the sample theses (served without an API key) |
| `scripts/run_demo_matches.py` | Re-creates the saved results (needs an API key) |

```text
.
├── .env                ← placeholder Neo4j settings (no real password)
├── .env.local          ← your real password, not in git (.env.* is ignored)
├── compose.yaml        ← Neo4j 5 in Docker
├── pyproject.toml
├── data/
│   ├── raw/            ← TTO PDFs (Life Sciences, Physical Sciences)
│   ├── demo/           ← demo dataset, sample theses, saved results
│   ├── cache/          ← fetched patent pages, not in git
│   ├── validation/     ← known cases for checking the pipeline
│   └── processed/      ← crawler output and links.json, not in git
├── docs/
├── src/
└── tests/
```

## Run the full demo (one click, macOS)

Needs Docker Desktop, Python 3.10+, Node.js 20+ and git.

```bash
mkdir vc-demo && cd vc-demo
git clone https://github.com/ENGG-119-group-5/backend.git
```

Then double-click `backend/Start Demo.command` in Finder (or run `"backend/Start Demo.command"`). It clones the [web app](https://github.com/ENGG-119-group-5/webapp) next to `backend/` if it is missing, installs the Python and Node packages on the first run, starts Neo4j, loads the demo data, starts the API and the website, and opens http://localhost:3000. Close the window to stop everything.

If you already have the web app, put it next to `backend/` in a folder named `web-app` or `webapp`.

## Setup (once)

Needs Python 3.10+ and Docker Desktop.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
mkdir -p data/processed
```

`.env` holds a placeholder password (`your_password`) that works for local development. To use a different password, put `NEO4J_PASSWORD=...` in `.env.local`; it overrides `.env` and is not committed.

## Start Neo4j

```bash
docker compose up -d                       # add: --env-file .env --env-file .env.local  if you use .env.local
docker compose ps                          # wait until the status shows "healthy"
```

Neo4j Browser: http://localhost:7474 (user `neo4j`, password from `.env`).

## Run the pipeline

Run from the repo root:

```bash
# 1. Schema (once)
python src/load_to_neo4j.py schema

# 2. Crawl the TTO PDFs (category comes from each file name; repeats are merged)
python src/tto_crawler.py data/raw/Life-Sciences.pdf data/raw/Physical-Sciences.pdf \
  -o data/processed/technologies.json

# 3. Fetch the real USPTO records for the numbers on those pages (about a minute; cached after)
python src/fetch_patents.py data/processed/technologies.json -o data/processed/uspto_patents.json

# 4. Load both sides
python src/load_to_neo4j.py tto data/processed/technologies.json
python src/load_to_neo4j.py patents data/processed/uspto_patents.json

# 5. Link technologies to patents
python src/link_v1.py data/processed/technologies.json data/processed/uspto_patents.json \
  -o data/processed/links.json --neo4j
```

The loader accepts `--dry-run`. The linker writes to Neo4j only with `--neo4j`. Both are rerunnable.

## Demo dataset (real data)

The demo runs on the output of the pipeline above, committed in `data/demo/` so nobody needs the network:

- `technologies_dartmouth.json`: all **41** technologies in Dartmouth's Life Sciences and Physical Sciences licensing decks.
- `uspto_patents_dartmouth.json`: the **20** real USPTO records (7 grants, 13 published applications) behind the US numbers on those pages.

The linker merges them: 20 confirmed links on 17 technologies. The merge finds things the TTO pages don't say: two listed "applications" have since been granted (one co-owned with a company), and one page links another technology's patent (held as `uncertain`). Details: data contract, section 11.

```bash
scripts/load_demo.sh     # WARNING: deletes everything in the graph first, then loads the demo data
```

To go back to the test fixtures, run `python src/load_to_neo4j.py reset` and follow "Tests" below.

## Run the API

```bash
uvicorn api.main:app --app-dir src --reload --reload-dir src   # http://localhost:8000/docs
curl "http://localhost:8000/search?q=&type=technology&limit=5"
curl "http://localhost:8000/technology/2018-168"
```

## Thesis matching (MVP)

`POST /match` takes an investment-thesis PDF and returns every technology labelled **strong / potential / none**, with area, problem, stage and deal fit scores. Each score comes with a quote from the technology's merged TTO + USPTO record, and the code checks every quote really is in that record. One Claude call (`claude-opus-5-5`) does the scoring (`src/api/matcher.py`). The rest is plain code.

```bash
curl -F "file=@data/demo/theses/immune-engineering-thesis.pdf" localhost:8000/match
```

- **Sample theses:** an immune-engineering therapeutics fund (fits the Life Sciences deck) and an electrification materials fund (fits the Physical Sciences deck). `GET /samples` lists them. Their **saved results** in `data/demo/results/` are returned immediately, with **no API key and no cost**, so anyone can run the demo from a fresh clone.
- **Your own thesis:** needs an Anthropic API key. Put it in `.env.local` (gitignored, never commit it) and restart the API:
  ```bash
  echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env.local
  ```
  One run reads all 41 technologies, takes 1–3 minutes and costs roughly $0.50–1. Set a monthly spend limit in the Anthropic Console if you share the key.
- **Saved results:** if you change the demo data, the prompt or a sample PDF, regenerate them with `python scripts/run_demo_matches.py` (needs the key and `scripts/load_demo.sh`).

The web app expects the API at `http://localhost:8000` (`NEXT_PUBLIC_API_BASE_URL` in the web app's `.env.local`). CORS allows `http://localhost:3000` by default; change it with `CORS_ORIGINS`.

## Tests

```bash
pytest -rs
```

- **Unit tests** (linking, keys, scoring) need nothing else.
- **API tests** (`tests/test_api.py`) need Neo4j running with the **test fixtures** loaded (not the demo dataset). They only read. Without Neo4j they are skipped, and the reason is printed. To run them:

  ```bash
  python src/load_to_neo4j.py schema
  python src/load_to_neo4j.py tto tests/fixtures/technologies_life_sciences.json
  python src/load_to_neo4j.py patents tests/fixtures/uspto_patents_test.json
  python src/link_v1.py tests/fixtures/technologies_life_sciences.json \
    tests/fixtures/uspto_patents_test.json -o data/processed/links.json --neo4j
  pytest -rs
  ```

CI (`.github/workflows/ci.yml`) does exactly this on every pull request, with a Neo4j service container and `REQUIRE_NEO4J=1`, so the API tests cannot silently skip there.

## Expected linking result with the test fixtures

```
confirmed 2018-168 -> US-10113979      (patent number)
confirmed 2018-168 -> US-APP-17264691  (application number)
confirmed 2021-023 -> US-APP-18359373  (application number, page label was wrong)
uncertain 2021-026 -> US-APP-17264691  (publication number only, conflict -> human review)
US-99999999: no link (negative control)
```

## Check in Neo4j Browser

```cypher
// The milestone 9 check: one technology, its people, its patents
MATCH (t:Technology {tto_id: '2018-168'})
OPTIONAL MATCH (i:Inventor)-[:LISTED_ON]->(t)
OPTIONAL MATCH (t)-[l:PROTECTED_BY]->(p:Patent)
RETURN t.title, collect(DISTINCT i.name) AS people, collect(DISTINCT p.patent_key) AS patents;

// Review queue
MATCH (t:Technology)-[l:POSSIBLY_PROTECTED_BY]->(p:Patent)
RETURN t.tto_id, p.patent_key, l.conflicts, l.review_status;

// Rerun check: run the loaders twice, this count must not change
MATCH (n) RETURN labels(n)[0] AS label, count(*) ORDER BY label;
```

## Known limits (v1)

- Exact identifiers only. PCT (5), provisional (6) and "portfolio" pages (4) cannot link by number. Name matching comes in v2.
- People are not merged across sources yet: `tto:randy noelle` and `tto:randolph noelle` are two nodes (v2: `SAME_AS`).
- The recency part of the IP score is measured from today's date, so scores drift slightly over time.
- The test fixtures are **not real USPTO data**. Remove them from the database before the demo:
  ```cypher
  MATCH (p:Patent) WHERE 'test_fixture' IN p.quality_flags DETACH DELETE p;
  MATCH (i:Inventor {source: 'uspto'}) WHERE NOT (i)--() DELETE i;
  MATCH (a:Assignee) WHERE NOT (a)--() DELETE a;
  ```
