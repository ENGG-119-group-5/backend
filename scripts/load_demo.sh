#!/usr/bin/env bash
# Load the demo dataset (data/demo/) into Neo4j:
#   41 real Dartmouth TTO listings (both licensing decks, read by src/tto_crawler.py)
#   + the real USPTO records for the patent numbers on those pages (src/fetch_patents.py)
# WARNING: this first deletes everything in the graph.
# Usage (from the repo root, venv active, Neo4j running):  scripts/load_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."

TECHS=data/demo/technologies_dartmouth.json
PATENTS=data/demo/uspto_patents_dartmouth.json

python src/load_to_neo4j.py reset
python src/load_to_neo4j.py schema
python src/load_to_neo4j.py tto "$TECHS"
python src/load_to_neo4j.py patents "$PATENTS"
mkdir -p data/processed
python src/link_v1.py "$TECHS" "$PATENTS" -o data/processed/links_demo.json --neo4j | tail -n 2
