"""
icd10_client.py — ICD-10-CM live lookup via NLM API.

Two capabilities:
  1. lookup_description(code)          → full description string for a known ICD-10-CM code
  2. search_icd10_for_drug(name, cls)  → top ICD-10-CM matches for an unknown drug (Step 3)

API: https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search
Free, no key required. LRU-cached. 5-second timeout — fails gracefully (returns "" or []).

Response format from NLM API:
  [total_count, [code_list], {}, [[code, name], ...]]
  data[3] contains the [code, name] pairs.
"""

import requests
from functools import lru_cache

_BASE    = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
_TIMEOUT = 5

# ── Drug class → clinical search term mapping ─────────────────────────────────
# Used by search_icd10_for_drug to translate RxNorm drug class into a
# clinically meaningful ICD-10 search term.
_CLASS_TO_TERM: dict[str, str] = {
    "antidiabetic":         "diabetes mellitus",
    "biguanide":            "type 2 diabetes mellitus",
    "insulin":              "diabetes mellitus",
    "thiazolidinedione":    "type 2 diabetes mellitus",
    "sulfonylurea":         "type 2 diabetes mellitus",
    "glp-1":                "type 2 diabetes mellitus",
    "sglt":                 "type 2 diabetes mellitus",
    "dpp-4":                "type 2 diabetes mellitus",
    "antihypertensive":     "hypertension",
    "ace inhibitor":        "hypertension",
    "arb":                  "hypertension",
    "angiotensin":          "hypertension",
    "beta blocker":         "hypertension",
    "beta-1":               "hypertension",
    "calcium channel":      "hypertension",
    "statin":               "hyperlipidemia",
    "hmg-coa":              "hyperlipidemia",
    "fibrate":              "hyperlipidemia",
    "anticoagulant":        "venous thromboembolism",
    "antiplatelet":         "coronary artery disease",
    "ssri":                 "major depressive disorder",
    "snri":                 "major depressive disorder",
    "antidepressant":       "depressive disorder",
    "anxiolytic":           "anxiety disorder",
    "benzodiazepine":       "anxiety disorder",
    "anticonvulsant":       "epilepsy",
    "antiepileptic":        "epilepsy",
    "bronchodilator":       "asthma",
    "beta-2 agonist":       "asthma",
    "leukotriene":          "asthma",
    "corticosteroid":       "inflammatory disorder",
    "steroid":              "inflammatory disorder",
    "proton pump":          "gastroesophageal reflux",
    "ppi":                  "gastroesophageal reflux",
    "h2 blocker":           "peptic ulcer",
    "thyroid":              "hypothyroidism",
    "loop diuretic":        "heart failure",
    "thiazide":             "hypertension",
    "diuretic":             "edema",
    "opioid":               "chronic pain",
    "analgesic":            "pain",
    "muscle relaxant":      "muscle spasm",
    "antibiotic":           "bacterial infection",
    "antifungal":           "fungal infection",
    "antiviral":            "viral infection",
    "antihistamine":        "allergic rhinitis",
    "antipsychotic":        "schizophrenia",
    "mood stabilizer":      "bipolar disorder",
    "bisphosphonate":       "osteoporosis",
    "alpha blocker":        "benign prostatic hyperplasia",
    "5-alpha reductase":    "benign prostatic hyperplasia",
    "antiemetic":           "nausea",
    "iron":                 "iron deficiency anemia",
    "vitamin d":            "vitamin d deficiency",
    "antirheumatic":        "rheumatoid arthritis",
    "dmard":                "rheumatoid arthritis",
}


def _extract_search_term(drug_class: str) -> str:
    """Map a drug class string to a clinical ICD-10 search term. Returns '' if no match."""
    cls_lower = drug_class.lower()
    for keyword, term in _CLASS_TO_TERM.items():
        if keyword in cls_lower:
            return term
    return ""


def _call_api(terms: str, max_list: int) -> list[list[str]]:
    """
    Call NLM ICD-10-CM API and return list of [code, name] pairs.
    Returns [] on any error.
    """
    try:
        r = requests.get(
            _BASE,
            params={"sf": "code,name", "terms": terms, "maxList": max_list},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if data and len(data) > 3 and data[3]:
            return data[3]
    except Exception:
        pass
    return []


@lru_cache(maxsize=4096)
def lookup_description(code: str) -> str:
    """
    Return the full description for a known ICD-10-CM code.
    Uses exact-match filter on the NLM search results.
    Returns '' if not found or API unavailable.
    """
    if not code:
        return ""
    code = code.strip().upper()
    if code in ("", "N/A", "NAN", "NONE"):
        return ""

    pairs = _call_api(code, 20)
    for pair in pairs:
        if pair[0].upper() == code:
            return pair[1]
    return ""


@lru_cache(maxsize=1024)
def search_icd10_for_drug(generic_name: str, drug_class: str, max_results: int = 4) -> tuple:
    """
    Search ICD-10-CM for an unknown drug using drug class → clinical term mapping.
    Falls back to searching by generic name if no class match.

    Returns a tuple of dicts (hashable for lru_cache):
      ({"code": "...", "description": "..."}, ...)
    Empty tuple if API unavailable or no results.
    """
    term = _extract_search_term(drug_class)
    if not term and generic_name:
        term = generic_name.strip()
    if not term or len(term) < 3:
        return ()

    pairs = _call_api(term, max_results)
    return tuple({"code": p[0], "description": p[1]} for p in pairs[:max_results])
