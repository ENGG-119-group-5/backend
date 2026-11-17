#!/usr/bin/env bash
# Load the SYNTHETIC demo dataset (data/demo/) into Neo4j.
# WARNING: this first deletes everything in the graph.
# Usage (from the repo root, venv active, Neo4j running):  scripts/load_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python src/load_to_neo4j.py reset
python src/load_to_neo4j.py schema
python src/load_to_neo4j.py tto data/demo/technologies_demo.json
python src/load_to_neo4j.py patents data/demo/uspto_patents_demo.json
mkdir -p data/processed
python src/link_v1.py data/demo/technologies_demo.json data/demo/uspto_patents_demo.json \
  -o data/processed/links_demo.json --neo4j | tail -n 2
