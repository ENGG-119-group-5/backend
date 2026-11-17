"""Run the two sample theses through Claude once and save the results to data/demo/results/.

The API returns these saved results for the sample PDFs, so anyone can see the demo
without an API key. Rerun this only when the demo data, the prompt or the PDFs change.

Needs: Neo4j with the demo data (scripts/load_demo.sh) and ANTHROPIC_API_KEY in .env.local.
Usage (repo root, venv active):  python scripts/run_demo_matches.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402

main.RESULTS_DIR = Path("/nonexistent")   # ignore old saved results: force a live Claude call
out_dir = main.DEMO_DIR / "results"
out_dir.mkdir(exist_ok=True)

with TestClient(main.app) as client:
    for name in main.SAMPLES:
        pdf = (main.DEMO_DIR / "theses" / name).read_bytes()
        print(f"Matching {name} (this takes about a minute)...")
        r = client.post("/match", files={"file": (name, pdf, "application/pdf")})
        if r.status_code != 200:
            sys.exit(f"  failed: {r.status_code} {r.text}")
        result = r.json()
        path = out_dir / name.replace(".pdf", ".json")
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        labels = Counter(m["label"] for m in result["matches"])
        fits = [f for m in result["matches"] for f in m["fits"] if f["quote"]]
        print(f"  {dict(labels)} | quotes verified: {sum(f['quoteVerified'] for f in fits)}/{len(fits)} "
              f"| unassessed: {result['unassessedIds']} -> {path}")
