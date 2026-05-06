"""
ndc_client.py — openFDA Drug NDC API client.
API: https://api.fda.gov/drug/ndc.json  (free, no key required)

Used when MedicationsCodeSystemName = "NDC" in the structured input file.
Lookups are cached per NDC code for the lifetime of the app session.
Falls back gracefully when offline.
"""

import re
import requests
from functools import lru_cache

FDA_NDC_URL = "https://api.fda.gov/drug/ndc.json"
TIMEOUT     = 6   # seconds

# Code system names that indicate an NDC value in MedicationsCode
NDC_SYSTEM_NAMES = {
    "ndc",
    "national drug code",
    "ndc code",
    "ndccode",
    "ndc11",
    "ndc10",
    "http://hl7.org/fhir/sid/ndc",
    "2.16.840.1.113883.6.69",     # OID for NDC
}


def _normalize_ndc(raw: str) -> list[str]:
    """
    Return candidate NDC strings to try against the FDA API.
    Handles dashes, leading zeros, and 10- vs 11-digit formats.
    """
    digits_only = re.sub(r"\D", "", raw)
    candidates = [raw.strip()]           # try as-is first

    # If it has dashes, also try without
    if "-" in raw:
        candidates.append(digits_only)

    # Common NDC segment formats: 5-4-2, 5-3-2, 4-4-2, 5-4-1 → also try 11-digit zero-padded
    if len(digits_only) == 10:
        candidates.append("0" + digits_only)    # pad to 11 digits
    if len(digits_only) == 11:
        candidates.append(digits_only[1:])      # try 10-digit

    return list(dict.fromkeys(candidates))      # deduplicate, preserve order


def check_ndc_api_available() -> bool:
    """Quick check if openFDA NDC API is reachable."""
    try:
        r = requests.get(FDA_NDC_URL, params={"search": 'generic_name:"metformin"', "limit": "1"}, timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@lru_cache(maxsize=512)
def lookup_ndc(ndc_raw: str) -> dict:
    """
    Query openFDA Drug NDC API for a given NDC code.
    Cached per raw NDC string — same code won't re-query in the same session.

    Returns dict:
        found               (bool)
        ndc                 (str)   — input NDC
        generic_name        (str)
        brand_name          (str)
        dosage_form         (str)   e.g. "TABLET"
        route               (str)   e.g. "ORAL"
        active_ingredients  (list)  — list of {"name": ..., "strength": ...}
        labeler             (str)   — manufacturer
        error               (str|None)
    """
    result = {
        "found":              False,
        "ndc":                ndc_raw,
        "generic_name":       "",
        "brand_name":         "",
        "dosage_form":        "",
        "route":              "",
        "active_ingredients": [],
        "labeler":            "",
        "error":              None,
    }

    candidates = _normalize_ndc(ndc_raw)

    for candidate in candidates:
        # Try package_ndc (full NDC including package segment)
        for search_field in ("packaging.package_ndc", "product_ndc"):
            try:
                r = requests.get(
                    FDA_NDC_URL,
                    params={
                        "search": f'{search_field}:"{candidate}"',
                        "limit": "1",
                    },
                    timeout=TIMEOUT,
                )

                if r.status_code == 404:
                    continue    # not found with this field/candidate

                r.raise_for_status()
                data = r.json()
                results_list = data.get("results", [])

                if not results_list:
                    continue

                hit = results_list[0]

                result["found"]        = True
                result["generic_name"] = hit.get("generic_name", "").lower().strip()
                result["brand_name"]   = hit.get("brand_name", "").strip()
                result["dosage_form"]  = hit.get("dosage_form", "").strip()
                result["labeler"]      = hit.get("labeler_name", "").strip()

                # Route: may be a list
                routes = hit.get("route", [])
                result["route"] = routes[0] if routes else ""

                # Active ingredients
                ingredients = hit.get("active_ingredients", [])
                result["active_ingredients"] = [
                    {"name": i.get("name", ""), "strength": i.get("strength", "")}
                    for i in ingredients
                ]

                return result

            except requests.Timeout:
                result["error"] = "openFDA NDC API timeout — check internet connection."
                return result
            except requests.ConnectionError:
                result["error"] = "openFDA NDC API unreachable — no internet connection."
                return result
            except requests.HTTPError as e:
                if r.status_code == 404:
                    continue
                result["error"] = f"openFDA NDC API error: {e}"
                return result
            except Exception as e:
                result["error"] = f"openFDA NDC API error: {e}"
                return result

    # All candidates tried — not found
    result["error"] = f"NDC '{ndc_raw}' not found in openFDA database. Verify NDC format."
    return result
