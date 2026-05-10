"""
ndc_client.py — openFDA Drug NDC API client.
API: https://api.fda.gov/drug/ndc.json  (free, no key required)

Rate limits:
  Without API key: 240 requests/minute, 1000 requests/day
  With API key:    240 requests/minute, no daily limit  ← recommended for batch use

Get a free API key at: https://open.fda.gov/apis/authentication/

To set your API key — run this once in Command Prompt before starting the app:
  set OPENFDA_API_KEY=your_key_here

Or set it permanently in Windows environment variables.

Lookups are cached per NDC code — same NDC won't re-query in the same session.
429 rate limit errors are retried automatically with exponential backoff.
"""

import os
import re
import time
import requests
from functools import lru_cache

FDA_NDC_URL = "https://api.fda.gov/drug/ndc.json"
TIMEOUT     = 8    # seconds per request

# Free API key from https://open.fda.gov/apis/authentication/
# Set via: set OPENFDA_API_KEY=your_key_here  (in Command Prompt before running app)
OPENFDA_API_KEY = os.environ.get("OPENFDA_API_KEY", "CLaoyTZACvszQOSGYxVW5vE2H5x6ZGNhkq6tlvP5").strip()

# Retry settings for 429 rate limit errors
MAX_RETRIES  = 3
RETRY_DELAYS = [2, 5, 10]   # seconds to wait before each retry

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
    Return candidate NDC strings to try against the openFDA API.

    openFDA stores NDC codes in dashed format only (e.g. "67877-0446-90").
    Undashed numeric strings (e.g. "67877044690") will never match unless
    converted to the dashed form first.

    Segments for 11-digit NDC (always 5-4-2):
        NNNNN-NNNN-NN

    Segments for 10-digit NDC (three possible labeler/product splits):
        NNNN-NNNN-NN   (4-4-2)
        NNNNN-NNN-NN   (5-3-2)
        NNNNN-NNNN-N   (5-4-1)

    All formats are tried; duplicates removed.
    """
    digits_only = re.sub(r"\D", "", raw)
    candidates: list[str] = []

    d = digits_only

    if len(d) == 11:
        # Standard modern format: 5-4-2
        candidates.append(f"{d[0:5]}-{d[5:9]}-{d[9:11]}")
        # Also try stripping leading zero to get 10-digit then dash it
        d10 = d[1:]  # drop leading zero
        candidates.append(f"{d10[0:4]}-{d10[4:8]}-{d10[8:10]}")  # 4-4-2
        candidates.append(f"{d10[0:5]}-{d10[5:8]}-{d10[8:10]}")  # 5-3-2
    elif len(d) == 10:
        # Three standard 10-digit splits
        candidates.append(f"{d[0:4]}-{d[4:8]}-{d[8:10]}")   # 4-4-2
        candidates.append(f"{d[0:5]}-{d[5:8]}-{d[8:10]}")   # 5-3-2
        candidates.append(f"{d[0:5]}-{d[5:9]}-{d[9:10]}")   # 5-4-1
        # Also try zero-padded to 11 then split 5-4-2
        d11 = "0" + d
        candidates.append(f"{d11[0:5]}-{d11[5:9]}-{d11[9:11]}")

    # Always include the raw value and bare digits as final fallbacks
    candidates.append(raw.strip())
    candidates.append(d)

    return list(dict.fromkeys(c for c in candidates if c))


def check_ndc_api_available() -> bool:
    """Quick check if openFDA NDC API is reachable."""
    try:
        params = {"search": 'generic_name:"metformin"', "limit": "1"}
        if OPENFDA_API_KEY:
            params["api_key"] = OPENFDA_API_KEY
        r = requests.get(FDA_NDC_URL, params=params, timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _get_with_retry(url: str, params: dict) -> requests.Response | None:
    """
    GET request with automatic retry on 429 (rate limit).
    Waits RETRY_DELAYS[attempt] seconds before each retry.
    Returns Response or None if all retries exhausted.
    """
    if OPENFDA_API_KEY:
        params = {**params, "api_key": OPENFDA_API_KEY}

    last_response = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAYS[attempt]
                    time.sleep(wait)
                    continue
                else:
                    last_response = r
                    break
            return r   # success or non-429 error
        except requests.Timeout:
            raise
        except requests.ConnectionError:
            raise

    return last_response   # returns 429 response after all retries


@lru_cache(maxsize=512)
def lookup_ndc(ndc_raw: str) -> dict:
    """
    Query openFDA Drug NDC API for a given NDC code.
    Retries automatically on 429 rate limit with exponential backoff.
    Cached per raw NDC string — same code won't re-query in the same session.

    Returns dict:
        found               (bool)
        ndc                 (str)
        rxcui               (str)   — from openfda.rxcui if available
        generic_name        (str)
        brand_name          (str)
        dosage_form         (str)
        route               (str)
        active_ingredients  (list)
        labeler             (str)
        error               (str|None)
    """
    result = {
        "found":              False,
        "ndc":                ndc_raw,
        "rxcui":              "",
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
        for search_field in ("packaging.package_ndc", "product_ndc"):
            try:
                r = _get_with_retry(
                    FDA_NDC_URL,
                    {"search": f'{search_field}:"{candidate}"', "limit": "1"},
                )

                if r is None:
                    result["error"] = "openFDA API unreachable."
                    return result

                if r.status_code == 429:
                    result["error"] = (
                        "openFDA rate limit exceeded (429). "
                        "Get a free API key at open.fda.gov/apis/authentication/ "
                        "and set OPENFDA_API_KEY environment variable to increase limits."
                    )
                    return result

                if r.status_code == 404:
                    continue

                r.raise_for_status()
                data         = r.json()
                results_list = data.get("results", [])

                if not results_list:
                    continue

                hit = results_list[0]

                result["found"]        = True
                result["generic_name"] = hit.get("generic_name", "").lower().strip()
                result["brand_name"]   = hit.get("brand_name", "").strip()
                result["dosage_form"]  = hit.get("dosage_form", "").strip()
                result["labeler"]      = hit.get("labeler_name", "").strip()

                routes = hit.get("route", [])
                result["route"] = routes[0] if routes else ""

                ingredients = hit.get("active_ingredients", [])
                result["active_ingredients"] = [
                    {"name": i.get("name", ""), "strength": i.get("strength", "")}
                    for i in ingredients
                ]

                # RXCUI from openFDA openfda section
                openfda_section = hit.get("openfda", {})
                rxcui_list      = openfda_section.get("rxcui", [])
                result["rxcui"] = str(rxcui_list[0]).strip() if rxcui_list else ""

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
                result["error"] = f"openFDA NDC API HTTP error: {e}"
                return result
            except Exception as e:
                result["error"] = f"openFDA NDC API error: {e}"
                return result

    result["error"] = f"NDC '{ndc_raw}' not found in openFDA database. Verify NDC format."
    return result
