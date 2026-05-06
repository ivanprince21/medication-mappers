"""
rxnorm_client.py — Free RxNorm API client (NLM). No API key needed.
API docs: https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html

Lookups are cached per RXCUI for the lifetime of the app session.
Falls back gracefully when offline — returns found=False with error message.
"""

import re
import requests
from functools import lru_cache

RXNAV_BASE  = "https://rxnav.nlm.nih.gov/REST"
RXCLASS_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json"
TIMEOUT     = 6  # seconds per request

# ── RXCUI detection patterns ─────────────────────────────────────────────────
# Priority order — first match wins
_RXCUI_PATTERNS = [
    re.compile(r'\bRXCUI\s*[=:]\s*(\d+)',  re.IGNORECASE),  # RXCUI:12345 or RXCUI=12345
    re.compile(r'\bRXN\s*[=:]\s*(\d+)',    re.IGNORECASE),  # RXN:12345
    re.compile(r'\[(\d{3,8})\]'),                            # [12345]
    re.compile(r'\(rxcui[=:\s]+(\d+)\)',   re.IGNORECASE),  # (rxcui 12345)
    re.compile(r'^\s*(\d{3,8})\s*$'),                       # pure numeric line
]


def extract_rxcui(text: str) -> str | None:
    """
    Detect an RXCUI number in an input line.
    Returns the RXCUI string or None.

    Supported input formats:
        860975                    ← bare number (whole line)
        RXCUI:860975
        RXCUI=860975
        RXN:860975
        Metformin 500mg [860975]
        Metformin RXCUI:860975 500mg
    """
    for pattern in _RXCUI_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
    return None


def check_api_available() -> bool:
    """Return True if RxNorm API is reachable (fast 3-second check)."""
    try:
        r = requests.get(f"{RXNAV_BASE}/version.json", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@lru_cache(maxsize=512)
def lookup_rxcui(rxcui: str) -> dict:
    """
    Query RxNorm API for full drug information by RXCUI number.
    Results are cached — same RXCUI won't hit the API twice per session.

    Returns dict:
        found       (bool)   — True if RXCUI resolved
        rxcui       (str)    — input RXCUI
        name        (str)    — full RxNorm concept name
        generic_name(str)    — lowercase generic / ingredient name
        brand_names (list)   — list of lowercase brand names
        drug_class  (str)    — drug class from ATC (may be empty)
        tty         (str)    — RxNorm term type (IN, SCD, BN, etc.)
        error       (str)    — error message if failed, else None
    """
    result = {
        "found":        False,
        "rxcui":        rxcui,
        "name":         "",
        "generic_name": "",
        "brand_names":  [],
        "drug_class":   "",
        "tty":          "",
        "error":        None,
    }

    try:
        # ── Step 1: Get concept properties ────────────────────────────────────
        r1 = requests.get(
            f"{RXNAV_BASE}/rxcui/{rxcui}/properties.json",
            timeout=TIMEOUT
        )
        r1.raise_for_status()
        props = r1.json().get("properties")

        if not props or not props.get("name"):
            result["error"] = f"RXCUI {rxcui} not found in RxNorm database."
            return result

        result["found"] = True
        result["name"]  = props.get("name", "")
        result["tty"]   = props.get("tty", "")

        # ── Step 2: Get ingredient (generic name) ─────────────────────────────
        r2 = requests.get(
            f"{RXNAV_BASE}/rxcui/{rxcui}/related.json",
            params={"tty": "IN"},
            timeout=TIMEOUT
        )
        r2.raise_for_status()
        groups = r2.json().get("relatedGroup", {}).get("conceptGroup", [])

        for grp in groups:
            concepts = grp.get("conceptProperties", [])
            if concepts:
                result["generic_name"] = concepts[0]["name"].lower().strip()
                break

        # Fallback: derive generic from concept name + TTY
        if not result["generic_name"]:
            tty  = result["tty"]
            name = result["name"]
            if tty == "IN":
                # Name IS the ingredient
                result["generic_name"] = name.lower().strip()
            elif tty in ("SCD", "SBD", "GPCK", "BPCK"):
                # "Metformin 500 MG Oral Tablet" — extract text before first digit
                m = re.match(r'^([A-Za-z][A-Za-z /\-]+?)(?:\s+\d)', name)
                if m:
                    result["generic_name"] = m.group(1).strip().lower()
                else:
                    result["generic_name"] = name.split()[0].lower()
            elif tty == "BN":
                # Brand name concept — store as-is; parser will resolve via BRAND_TO_GENERIC
                result["generic_name"] = name.lower().strip()
            else:
                result["generic_name"] = name.split()[0].lower()

        # ── Step 3: Get brand names (optional) ───────────────────────────────
        try:
            r3 = requests.get(
                f"{RXNAV_BASE}/rxcui/{rxcui}/related.json",
                params={"tty": "BN"},
                timeout=TIMEOUT
            )
            r3.raise_for_status()
            for grp in r3.json().get("relatedGroup", {}).get("conceptGroup", []):
                for c in grp.get("conceptProperties", []):
                    result["brand_names"].append(c["name"].lower().strip())
        except Exception:
            pass  # brand names are optional

        # ── Step 4: Get drug class via RxClass ATC (optional) ─────────────────
        try:
            r4 = requests.get(
                RXCLASS_URL,
                params={"rxcui": rxcui, "relaSource": "ATC"},
                timeout=TIMEOUT
            )
            r4.raise_for_status()
            drug_info_list = (
                r4.json()
                  .get("rxclassDrugInfoList", {})
                  .get("rxclassDrugInfo", [])
            )
            if drug_info_list:
                result["drug_class"] = (
                    drug_info_list[0]
                    .get("rxclassMinConceptItem", {})
                    .get("className", "")
                )
        except Exception:
            pass  # drug class is optional

    except requests.Timeout:
        result["error"] = "RxNorm API timeout — check internet connection."
    except requests.ConnectionError:
        result["error"] = "RxNorm API unreachable — no internet connection."
    except requests.RequestException as e:
        result["error"] = f"RxNorm API error: {e}"

    return result
