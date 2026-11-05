# Pipeline v0.1 — TTO → Neo4j → Linking

Follows `data_contract.md` v0.2.

## Files

| File | What it does |
| --- | --- |
| `normalize.py` | Shared rules for patent keys and name keys (one place, used by all scripts) |
| `load_to_neo4j.py` | Creates the schema, loads TTO technologies and USPTO patents. Rerunnable (`MERGE`) |
| `link_v1.py` | Links technologies to patents by exact identifiers. Writes `links.json`, optionally Neo4j |
| `test_fixtures/uspto_patents_test.json` | 4 **fake** patent records to test linking before the real USPTO data |
| `test_link_v1.py` | 7 tests: grant, mislabeled application, copy-paste conflict, negative control, keys |

```test
.
├── .gitignore          ← venv, __pycache__, .env, data/
├── .env.example        ← NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD (no real password)
├── pyproject.toml
├── README.md
├── data/               ← real inputs and outputs, not in git
│   ├── raw/            ← TTO PDFs
│   ├── cache/          ← cached USPTO responses (Mia)
│   └── processed/      ← technologies_*.json from the crawler
├── docs/
├── src/
└── tests/
```

## Run order

### Set up (once)

```bash
pip install -e ".[dev]"
cp .env .env.local             # then put your real NEO4J_PASSWORD in .env.local
mkdir -p data/raw data/processed
```

### Tests

```bash
pytest
```

### Docker

```bash
docker compose --env-file .env --env-file .env.local up -d
docker compose ps          # wait until the status shows "healthy"
```

### Python scripts and tests

```bash
# Schema (once)
python src/load_to_neo4j.py schema

# Crawl the TTO PDF
python src/tto_crawler.py data/raw/Life-Sciences.pdf --category "Life Sciences" \
  -o data/processed/technologies_life_sciences.json

# Load the TTO technologies
python src/load_to_neo4j.py tto data/processed/technologies_life_sciences.json

# Load the patents: test fixtures now, Mia's file later
python src/load_to_neo4j.py patents tests/fixtures/uspto_patents_test.json

# Linking
python src/link_v1.py data/processed/technologies_life_sciences.json \
  tests/fixtures/uspto_patents_test.json -o data/processed/links.json --neo4j
```

Every command accepts `--dry-run` (loader) or runs without `--neo4j` (linker) to check without a database.

## Expected result with the test fixtures

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
- The test fixtures are **not real USPTO data**. Remove them from the database before the demo:
  ```cypher
  MATCH (p:Patent) WHERE 'test_fixture' IN p.quality_flags DETACH DELETE p;
  MATCH (i:Inventor {source: 'uspto'}) WHERE NOT (i)--() DELETE i;
  MATCH (a:Assignee) WHERE NOT (a)--() DELETE a;
  ```
