"""
Shared key and name normalization (data_contract.md, section 5).
Every script uses these functions, so keys are always built the same way.
"""

import re
import unicodedata

TITLES = {"dr", "prof", "professor", "mr", "mrs", "ms"}
DEGREES = {"phd", "md", "mph", "mdphd", "msc", "ms", "ba", "bs"}


def digits(s):
    """'17/264,691' -> '17264691'."""
    return re.sub(r"\D", "", s or "")


def patent_key_from_ref(ref):
    """TTO IpRef -> patent_key, or None when the ref cannot exist in USPTO."""
    n = ref.get("number_normalized")
    t = ref.get("ip_type")
    if not n:
        return None
    if t == "granted_patent":
        return f"US-{digits(n)}"
    if t == "application":
        return f"US-APP-{digits(n)}"
    if t == "provisional":
        return f"US-PROV-{digits(n)}"
    if t == "pct":
        return f"WO-{n}"
    return None


def patent_key_from_patent(p):
    """USPTO Patent record -> patent_key (grant wins over application)."""
    if p.get("doc_type") == "grant" and p.get("patent_number"):
        return f"US-{digits(p['patent_number'])}"
    if p.get("application_number"):
        return f"US-APP-{digits(p['application_number'])}"
    return None


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def name_key(name):
    """'Dr. Randolph J. Noelle' -> 'randolph noelle'. First + last name only."""
    s = strip_accents(name or "").lower()
    s = s.replace("’", "'").replace("'", "")          # O’Toole -> otoole
    tokens = [t.strip(".,()") for t in s.split()]
    tokens = [t for t in tokens if t and t not in TITLES and t.replace(".", "").replace("/", "") not in DEGREES]
    tokens = [t for t in tokens if len(t.replace(".", "")) > 1]   # drop middle initials like "j."
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    return f"{tokens[0]} {tokens[-1]}"


def tto_inventor_id(person_name):
    return f"tto:{name_key(person_name)}"
