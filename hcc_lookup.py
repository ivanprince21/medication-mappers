"""
hcc_lookup.py — CMS-HCC Model v28 ICD-10-CM to HCC category lookup.

Data source: hcc_crosswalk.json (CMS Risk Adjustment crosswalk, bundled locally).
Works offline — no API required.

To add new ICD codes: edit hcc_crosswalk.json.
"""

import json
import os

_CROSSWALK_PATH = os.path.join(os.path.dirname(__file__), "hcc_crosswalk.json")

# Load once at import time
with open(_CROSSWALK_PATH, "r", encoding="utf-8") as _f:
    _RAW = json.load(_f)

# Strip meta key — keyed by ICD-10 code (uppercase, with dot)
HCC_MAP: dict[str, dict] = {
    k: v for k, v in _RAW.items() if not k.startswith("_")
}


def _normalize_icd(code: str) -> str:
    """Normalize ICD code: uppercase, strip whitespace."""
    return str(code).strip().upper()


def lookup_hcc(icd_code: str) -> dict:
    """
    Look up HCC info for a single ICD-10-CM code.

    Returns dict:
        found               (bool)
        hcc_category        (str)   e.g. "HCC85"
        hcc_label           (str)   e.g. "Congestive Heart Failure"
        model_hierarchy     (str)   e.g. "HCC85 (standalone)"
        hierarchy_description (str) plain-language hierarchy explanation
        high_value          (bool)  True if HCC carries significant RAF weight
    """
    code = _normalize_icd(icd_code)

    if code in HCC_MAP:
        entry = HCC_MAP[code]
        return {
            "found":                 True,
            "hcc_category":          entry.get("hcc_category", ""),
            "hcc_label":             entry.get("hcc_label", ""),
            "model_hierarchy":       entry.get("model_hierarchy", ""),
            "hierarchy_description": entry.get("hierarchy_description", ""),
            "high_value":            entry.get("high_value", False),
        }

    # Try prefix match: E11.9 not found → try E11 (some codes lack decimal specificity)
    prefix = code.split(".")[0]
    for map_code, entry in HCC_MAP.items():
        if map_code.startswith(prefix + "."):
            return {
                "found":                 True,
                "hcc_category":          entry.get("hcc_category", "") + "*",
                "hcc_label":             entry.get("hcc_label", "") + " (approximate — verify code)",
                "model_hierarchy":       entry.get("model_hierarchy", ""),
                "hierarchy_description": entry.get("hierarchy_description", "") + " NOTE: Matched by code prefix — verify exact ICD code.",
                "high_value":            entry.get("high_value", False),
            }

    return {
        "found":                 False,
        "hcc_category":          "No HCC",
        "hcc_label":             "Not mapped to HCC in CMS-HCC v28",
        "model_hierarchy":       "N/A",
        "hierarchy_description": "This ICD-10 code does not map to an HCC category in the CMS-HCC Model v28 crosswalk. It may still be clinically significant.",
        "high_value":            False,
    }


def lookup_hcc_for_codes(icd_codes: list[str]) -> list[dict]:
    """
    Look up HCC info for a list of ICD-10 codes.
    Returns a list of result dicts (same order as input).
    Empty or blank codes return a not-found result.
    """
    results = []
    for code in icd_codes:
        if not code or str(code).strip().lower() in ("", "nan", "none", "n/a"):
            results.append({
                "found":                 False,
                "hcc_category":          "",
                "hcc_label":             "",
                "model_hierarchy":       "",
                "hierarchy_description": "",
                "high_value":            False,
            })
        else:
            results.append(lookup_hcc(code))
    return results


def has_high_value_hcc(icd_codes: list[str]) -> bool:
    """Return True if any of the ICD codes maps to a high-value HCC."""
    return any(r["high_value"] for r in lookup_hcc_for_codes(icd_codes))
