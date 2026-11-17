# VC Due Diligence Tool: backend

[![CI](https://github.com/ENGG-119-group-5/backend/actions/workflows/ci.yml/badge.svg)](https://github.com/ENGG-119-group-5/backend/actions/workflows/ci.yml)

Pipeline v0.1 (TTO → Neo4j → linking) and the FastAPI API used by the [web app](https://github.com/ENGG-119-group-5/webapp). Data formats follow [`docs/data_contract.md`](docs/data_contract.md) (v0.3).

## Files

| File | What it does |
| --- | --- |
| `src/tto_crawler.py` | Reads a Dartmouth TTO licensing PDF (one technology per page) into Technology records |
| `src/normalize.py` | Shared rules for patent keys and name keys (one place, used by all scripts) |
| `src/load_to_neo4j.py` | Creates the schema, loads TTO technologies and USPTO patents. Rerunnable (`MERGE`) |
| `src/link_v1.py` | Links technologies to patents by exact identifiers. Writes `links.json`, optionally Neo4j |
| `src/config.py` | Neo4j settings, read from `.env` then `.env.local` |
| `src/api/` | FastAPI app (`main.py`), response models (`models.py`), rule-based IP score (`scoring.py`) |
| `tests/fixtures/technologies_life_sciences.json` | Frozen crawler output for the Life Sciences PDF (29 technologies) |
| `tests/fixtures/uspto_patents_test.json` | 4 **fake** patent records to test linking before the real USPTO data |
| `data/validation/spinout_cases.csv` | Known Dartmouth spin-outs with their expected patents and inventors |
| `data/demo/` | **Synthetic** demo dataset: 30 made-up TTO listings and 19 made-up USPTO patents |
| `scripts/load_demo.sh` | Replaces the graph with the demo dataset |

```text
.
├── .env                ← placeholder Neo4j settings (no real password)
├── .env.local          ← your real password, not in git (.env.* is ignored)
├── compose.yaml        ← Neo4j 5 in Docker
├── pyproject.toml
├── data/
│   ├── raw/            ← TTO PDFs
│   ├── validation/     ← known cases for checking the pipeline
│   └── processed/      ← crawler output and links.json, not in git
├── docs/
├── src/
└── tests/
```

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

# 2. Crawl the TTO PDF
python src/tto_crawler.py data/raw/Life-Sciences.pdf --category "Life Sciences" \
  -o data/processed/technologies_life_sciences.json

# 3. Load the TTO technologies
python src/load_to_neo4j.py tto data/processed/technologies_life_sciences.json

# 4. Load the patents (test fixtures until the USPTO loader exists)
python src/load_to_neo4j.py patents tests/fixtures/uspto_patents_test.json

# 5. Link technologies to patents
python src/link_v1.py data/processed/technologies_life_sciences.json \
  tests/fixtures/uspto_patents_test.json -o data/processed/links.json --neo4j
```

The loader accepts `--dry-run`. The linker writes to Neo4j only with `--neo4j`. Both are rerunnable.

## Demo dataset (synthetic)

The MVP demo runs on **made-up** data in `data/demo/`: 30 Dartmouth-style inventions (oncology, climate/energy hardware, and others) and 19 USPTO-style patents that the linker merges with them. Nothing in it describes a real invention, and the API never links it to real patent pages. Details: data contract, section 11.

```bash
scripts/load_demo.sh     # WARNING: deletes everything in the graph first, then loads the demo data
```

To go back to the real Life Sciences listings or the test fixtures, run `python src/load_to_neo4j.py reset` and follow "Run the pipeline" above.

## Run the API

```bash
uvicorn api.main:app --app-dir src --reload --reload-dir src   # http://localhost:8000/docs
curl "http://localhost:8000/search?q=&type=technology&limit=5"
curl "http://localhost:8000/technology/2018-168"
```

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
