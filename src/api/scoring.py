"""IP-potential score. PLACEHOLDER rubric (rubric-v0), built only from fields that
exist in the graph today. The team owns the real rubric: edit WEIGHTS and the
indicators in compute_ip_score(). Pure Python, no database or web imports.

Contract rules (docs/API_CONTRACT.md):
  contribution = normalized * weight * 100 (1 dp); weights sum to 1;
  computed = sum of contributions; effective = override.score or computed.
"""
from datetime import date

RUBRIC = "rubric-v0"
WEIGHTS = {
    "protection": 0.30,    # granted patent > application > nothing
    "link_conf": 0.15,     # best confidence among confirmed TTO<->patent links
    "links": 0.15,         # number of confirmed linked patents (caps at 3)
    "funding": 0.15,       # patent carries a government-interest statement
    "availability": 0.10,  # TTO status
    "recency": 0.15,       # newest grant/filing date (needs dates in the data)
}
assert abs(sum(WEIGHTS.values()) - 1) < 1e-9


def _norm(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 3)


def _year(v) -> int | None:
    try:
        return int(str(v)[:4]) if v else None
    except ValueError:
        return None


def _ind(key: str, label: str, value: str, normalized: float, source: dict | None = None) -> dict:
    w = WEIGHTS[key]
    d = {"key": key, "label": label, "value": value, "normalized": normalized,
         "weight": w, "contribution": round(normalized * w * 100, 1)}
    if source:
        d["source"] = source
    return d


def _src(p: dict | None) -> dict | None:
    if p and p.get("url"):
        return {"kind": "uspto", "label": f"USPTO record {p['number_label']}", "url": p["url"]}
    return None


def compute_ip_score(status: str, patents: list[dict], override: dict | None = None,
                     today: date | None = None) -> dict:
    """patents: confirmed links only, each {doc_type, number_label, url, grant_date,
    filing_date, has_funding, confidence}. Returns a camelCase dict matching IpScore."""
    this_year = (today or date.today()).year
    grants = [p for p in patents if p.get("doc_type") == "grant"]
    apps = [p for p in patents if p.get("doc_type") != "grant"]

    if grants:
        protection = _ind("protection", "Patent protection", "Granted US patent", 1.0, _src(grants[0]))
    elif apps:
        protection = _ind("protection", "Patent protection", "Published application only", 0.5, _src(apps[0]))
    else:
        protection = _ind("protection", "Patent protection", "No confirmed patent link", 0.0)

    confs = [p["confidence"] for p in patents if p.get("confidence") is not None]
    best = max(confs) if confs else None

    funded = next((p for p in patents if p.get("has_funding")), None)

    years = [y for p in patents for y in (_year(p.get("grant_date")), _year(p.get("filing_date"))) if y]
    newest = max(years) if years else None

    indicators = [
        protection,
        _ind("link_conf", "Link confidence",
             f"Best link confidence {best:.2f}" if best is not None else "No confirmed link",
             _norm(best) if best is not None else 0.0),
        _ind("links", "Confirmed linked patents", f"{len(patents)} linked", _norm(len(patents) / 3)),
        _ind("funding", "Federal funding signal",
             "Government-interest statement on patent" if funded else "No funding statement",
             1.0 if funded else 0.0, _src(funded)),
        _ind("availability", "Availability",
             "Available for license" if status == "available" else "Status unknown",
             1.0 if status == "available" else 0.5),
        _ind("recency", "Recent patent activity",
             f"Latest patent date {newest}" if newest else "No patent dates in data",
             _norm((newest - (this_year - 10)) / 10) if newest else 0.0),
    ]

    computed = round(sum(i["contribution"] for i in indicators), 1)
    ov = None
    if override and override.get("score") is not None:
        ov = {"score": round(float(override["score"]), 1), "reason": override.get("reason") or "",
              "analyst": override.get("analyst") or "", "at": override.get("at") or ""}
    return {"rubric": RUBRIC, "computed": computed, "indicators": indicators,
            "override": ov, "effective": ov["score"] if ov else computed}
