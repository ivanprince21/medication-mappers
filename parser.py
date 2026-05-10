"""
parser.py — Medication parsing, lookup, and enrichment pipeline.

Lookup flow per input row:
  1. Call external API based on MedicationsCodeSystemName:
       RxNorm → NLM RxNorm API  (returns: generic name, brand, class, RXCUI confirmed)
       NDC    → openFDA NDC API (returns: generic name, brand, dosage form, RXCUI if available)

  2. DUAL dictionary lookup (both run, RXCUI match takes priority):
       a. RXCUI match  — exact lookup by RXCUI stored in dictionary entries (fast, precise)
       b. Name match   — text match on generic name from API response
       If both find the SAME entry → confirmed, highest confidence
       If they find DIFFERENT entries → RXCUI match used, flagged for review
       If only one finds → use that result

  3. HCC enrichment — resolved ICD codes looked up in CMS-HCC v28 crosswalk (local, offline)

Note: MedicationsCode column contains the code VALUE (e.g. drug name for RxNorm, NDC number for NDC).
      The app calls the API to resolve it to a RXCUI/drug info — you do not need to provide RXCUI directly.

To add drugs:        edit medication_dictionary.json
To add ICD→HCC maps: edit hcc_crosswalk.json
"""

import re
import json
import os

from rxnorm_client import extract_rxcui, lookup_rxcui
from ndc_client    import lookup_ndc, NDC_SYSTEM_NAMES
from hcc_lookup    import lookup_hcc_for_codes, has_high_value_hcc
from icd10_client  import lookup_description, search_icd10_for_drug

# ── Load medication dictionary ────────────────────────────────────────────────
_DICT_PATH = os.path.join(os.path.dirname(__file__), "medication_dictionary.json")


def load_dictionary() -> dict:
    with open(_DICT_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


DRUG_DICT = load_dictionary()

# Brand name → generic key index
BRAND_TO_GENERIC: dict[str, str] = {}
for _g, _e in DRUG_DICT.items():
    for _b in _e.get("brand_names", []):
        BRAND_TO_GENERIC[_b.lower().strip()] = _g

# RXCUI → generic key index (for direct RXCUI-based lookup)
# Built from the "rxcui" field stored in each dictionary entry (populated by build_dictionary.py)
RXCUI_TO_GENERIC: dict[str, str] = {}
for _g, _e in DRUG_DICT.items():
    _rxcui = str(_e.get("rxcui", "")).strip()
    if _rxcui and _rxcui not in ("", "0", "None"):
        RXCUI_TO_GENERIC[_rxcui] = _g

# ── Constants ─────────────────────────────────────────────────────────────────
REQUIRED_INPUT_COLS = [
    "MedicationsID",
    "DocID",
    "DateOfService",
    "MedicationsCode",
    "MedicationsCodeSystemName",
    "MedicationsCodeDisplayName",
    "MedicationsCodeDisplayNameView",
    "DoseQuantity",
]

RXNORM_SYSTEM_NAMES = {
    "rxnorm", "rx norm", "rxn", "rxnorm code", "rxnormcode",
    "http://www.nlm.nih.gov/research/umls/rxnorm",
}

# ── Regex helpers ─────────────────────────────────────────────────────────────
_DOSAGE_RE   = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?|iu|mEq|%)\b", re.IGNORECASE)
_CLEAN_RE    = re.compile(r"[^\w\s.%/-]")
_SPACE_RE    = re.compile(r"\s+")
_RXCUI_STRIP = re.compile(
    r'\bRXCUI\s*[=:\s]\s*\d+|\bRXN\s*[=:\s]\s*\d+|\[\d+\]|\(\s*rxcui[^)]*\)',
    re.IGNORECASE
)


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = _CLEAN_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _extract_dosage(text: str) -> str:
    m = _DOSAGE_RE.search(text)
    return m.group(0).strip() if m else "Unknown"


def _extract_drug_name_text(text: str) -> str:
    t = _RXCUI_STRIP.sub(" ", text)
    t = _DOSAGE_RE.sub("", t)
    t = re.sub(r"\b(tablet|cap|capsule|tab|oral|er|xr|sr|cr|dr|hcl|otc)\b", "", t, flags=re.IGNORECASE)
    t = _CLEAN_RE.sub(" ", t)
    return _SPACE_RE.sub(" ", t).strip()


def _extract_strength_form(display_view: str, drug_name: str) -> str:
    if not display_view:
        return ""
    if drug_name:
        stripped = re.sub(re.escape(drug_name), "", display_view, count=1, flags=re.IGNORECASE).strip()
        if stripped:
            return stripped
    m = _DOSAGE_RE.search(display_view)
    return display_view[m.start():].strip() if m else display_view


def _pad(lst: list, size: int, fill: str = "") -> list:
    return (lst + [fill] * size)[:size]


# ── Local dictionary lookup ───────────────────────────────────────────────────
def lookup_by_rxcui(rxcui: str) -> str | None:
    """
    Exact RXCUI lookup against the dictionary RXCUI index.
    Returns the generic dict key or None.
    This is the fastest and most precise lookup path.
    """
    return RXCUI_TO_GENERIC.get(str(rxcui).strip())


def lookup_drug(name: str) -> tuple[str | None, str]:
    n = name.lower().strip()
    if not n:
        return None, ""
    if n in DRUG_DICT:
        return n, ""
    if n in BRAND_TO_GENERIC:
        return BRAND_TO_GENERIC[n], n
    for g in DRUG_DICT:
        if n.startswith(g) or g.startswith(n):
            return g, ""
    for b, g in BRAND_TO_GENERIC.items():
        if n.startswith(b) or b.startswith(n):
            return g, b
    for token in n.split():
        if len(token) < 4:
            continue
        if token in DRUG_DICT:
            return token, ""
        if token in BRAND_TO_GENERIC:
            return BRAND_TO_GENERIC[token], token
        for g in DRUG_DICT:
            if token in g or g in token:
                return g, ""
    return None, ""


# ── HCC enrichment ────────────────────────────────────────────────────────────
def _build_icd_columns(icd_codes: list[str]) -> dict:
    """
    Look up ICD-10-CM descriptions and HCC info for up to 4 ICD codes.
    Returns flat dict covering ICD Description + HCC columns for slots 1-4.
    """
    hcc_results = lookup_hcc_for_codes(icd_codes)
    high_value  = has_high_value_hcc(icd_codes)
    out = {}

    for i, (code, hcc) in enumerate(zip(icd_codes, hcc_results), start=1):
        out[f"ICD-10 Description {i}"]        = lookup_description(code) if code else ""
        out[f"HCC Category (ICD {i})"]        = hcc["hcc_category"]
        out[f"HCC Model Hierarchy (ICD {i})"] = hcc["model_hierarchy"]
        out[f"HCC Description (ICD {i})"]     = hcc["hcc_label"]

    out["High Value HCC Flag"] = "YES — Review" if high_value else "No"
    return out


# ── Drug info builders ────────────────────────────────────────────────────────
def _drug_info_from_dict(dict_key: str, dosage: str, strength_form: str,
                         brand_matched: str, data_source: str) -> dict:
    entry       = DRUG_DICT[dict_key]
    indications = _pad(entry.get("indications",        []), 3)
    conditions  = _pad(entry.get("related_conditions", []), 3)
    icd_codes   = _pad(entry.get("icd10_codes",        []), 4)

    brand_names   = entry.get("brand_names", [])
    brand_display = brand_matched.title() if brand_matched else (
        brand_names[0].title() if brand_names else ""
    )

    icd_cols = _build_icd_columns(icd_codes)

    return {
        "Normalized Generic Name":       entry["generic_name"].title(),
        "Brand Name Match":              brand_display,
        "Dosage":                        dosage,
        "Strength / Form":               strength_form or dosage,
        "Drug Class":                    entry.get("drug_class", ""),
        "Possible Indication 1":         indications[0],
        "Possible Indication 2":         indications[1],
        "Possible Indication 3":         indications[2],
        "Why Member May Take This Drug": entry.get("why_member_takes", ""),
        "Possible Related Condition 1":  conditions[0],
        "Possible Related Condition 2":  conditions[1],
        "Possible Related Condition 3":  conditions[2],
        "Possible ICD-10-CM Code 1":     icd_codes[0],
        "ICD-10 Description 1":          icd_cols.get("ICD-10 Description 1", ""),
        "HCC Category (ICD 1)":          icd_cols.get("HCC Category (ICD 1)", ""),
        "HCC Model Hierarchy (ICD 1)":   icd_cols.get("HCC Model Hierarchy (ICD 1)", ""),
        "HCC Description (ICD 1)":       icd_cols.get("HCC Description (ICD 1)", ""),
        "Possible ICD-10-CM Code 2":     icd_codes[1],
        "ICD-10 Description 2":          icd_cols.get("ICD-10 Description 2", ""),
        "HCC Category (ICD 2)":          icd_cols.get("HCC Category (ICD 2)", ""),
        "HCC Model Hierarchy (ICD 2)":   icd_cols.get("HCC Model Hierarchy (ICD 2)", ""),
        "HCC Description (ICD 2)":       icd_cols.get("HCC Description (ICD 2)", ""),
        "Possible ICD-10-CM Code 3":     icd_codes[2],
        "ICD-10 Description 3":          icd_cols.get("ICD-10 Description 3", ""),
        "HCC Category (ICD 3)":          icd_cols.get("HCC Category (ICD 3)", ""),
        "HCC Model Hierarchy (ICD 3)":   icd_cols.get("HCC Model Hierarchy (ICD 3)", ""),
        "HCC Description (ICD 3)":       icd_cols.get("HCC Description (ICD 3)", ""),
        "Possible ICD-10-CM Code 4":     icd_codes[3],
        "ICD-10 Description 4":          icd_cols.get("ICD-10 Description 4", ""),
        "HCC Category (ICD 4)":          icd_cols.get("HCC Category (ICD 4)", ""),
        "HCC Model Hierarchy (ICD 4)":   icd_cols.get("HCC Model Hierarchy (ICD 4)", ""),
        "HCC Description (ICD 4)":       icd_cols.get("HCC Description (ICD 4)", ""),
        "High Value HCC Flag":           icd_cols.get("High Value HCC Flag", "No"),
        "Confidence Level":              entry.get("confidence", ""),
        "Manual Review Flag":            "YES" if entry.get("manual_review") else "No",
        "Ambiguity Notes":               entry.get("ambiguity_note", ""),
        "Data Source":                   data_source,
    }


def _drug_info_api_only(api_name: str, api_brand: str, api_class: str,
                        api_ref: str, dosage: str, strength_form: str,
                        data_source: str) -> dict:
    """
    Drug resolved via API (RxNorm or NDC) but not in local dict.
    Attempts live ICD-10-CM search using drug class → clinical term mapping.
    HCC lookup is skipped (no reliable ICD codes).
    """
    # Live ICD-10 search (Step 3)
    icd_results = list(search_icd10_for_drug(
        api_name or "", api_class or "", max_results=4
    ))
    icd_results += [{}] * (4 - len(icd_results))   # pad to 4 slots

    def _code(i):  return icd_results[i].get("code", "") if icd_results[i] else ""
    def _desc(i):  return icd_results[i].get("description", "") if icd_results[i] else ""

    live_icd_found = bool(icd_results[0])
    icd_note = (
        "Possible ICD-10-CM codes from live NLM search — not verified against clinical context."
        if live_icd_found else
        "ICD-10/HCC mapping unavailable — add to medication_dictionary.json."
    )

    empty_hcc = {}
    for i in range(1, 5):
        empty_hcc[f"HCC Category (ICD {i})"]        = ""
        empty_hcc[f"HCC Model Hierarchy (ICD {i})"] = ""
        empty_hcc[f"HCC Description (ICD {i})"]     = ""

    return {
        "Normalized Generic Name":       api_name.title() if api_name else "",
        "Brand Name Match":              api_brand.title() if api_brand else "",
        "Dosage":                        dosage,
        "Strength / Form":               strength_form or dosage,
        "Drug Class":                    api_class,
        "Possible Indication 1":         "Not in local dictionary — see live ICD-10 search below" if live_icd_found else "Insufficient specificity — not in local dictionary",
        "Possible Indication 2":         "",
        "Possible Indication 3":         "",
        "Why Member May Take This Drug": (
            f"Drug identified via {api_ref}. "
            "Not yet mapped in medication_dictionary.json — add entry for full ICD and HCC mapping."
        ),
        "Possible Related Condition 1":  "Manual review required",
        "Possible Related Condition 2":  "",
        "Possible Related Condition 3":  "",
        "Possible ICD-10-CM Code 1":     _code(0) or "N/A — not in local dictionary",
        "ICD-10 Description 1":          _desc(0),
        **empty_hcc,
        "Possible ICD-10-CM Code 2":     _code(1),
        "ICD-10 Description 2":          _desc(1),
        "Possible ICD-10-CM Code 3":     _code(2),
        "ICD-10 Description 3":          _desc(2),
        "Possible ICD-10-CM Code 4":     _code(3),
        "ICD-10 Description 4":          _desc(3),
        "High Value HCC Flag":           "Unknown — Manual Review",
        "Confidence Level":              "Low",
        "Manual Review Flag":            "YES",
        "Ambiguity Notes":               f"Resolved via {api_ref}. {icd_note}",
        "Data Source":                   data_source,
    }


def _drug_info_unknown(parsed_name: str, dosage: str, reason: str) -> dict:
    empty_icd = {}
    for i in range(1, 5):
        empty_icd[f"ICD-10 Description {i}"]        = ""
        empty_icd[f"HCC Category (ICD {i})"]        = ""
        empty_icd[f"HCC Model Hierarchy (ICD {i})"] = ""
        empty_icd[f"HCC Description (ICD {i})"]     = ""
    return {
        "Normalized Generic Name":       "Unknown Medication",
        "Brand Name Match":              "",
        "Dosage":                        dosage,
        "Strength / Form":               "",
        "Drug Class":                    "Unknown",
        "Possible Indication 1":         "Insufficient specificity",
        "Possible Indication 2":         "",
        "Possible Indication 3":         "",
        "Why Member May Take This Drug": reason,
        "Possible Related Condition 1":  "Unknown",
        "Possible Related Condition 2":  "",
        "Possible Related Condition 3":  "",
        "Possible ICD-10-CM Code 1":     "N/A",
        **empty_icd,
        "Possible ICD-10-CM Code 2":     "",
        "Possible ICD-10-CM Code 3":     "",
        "Possible ICD-10-CM Code 4":     "",
        "High Value HCC Flag":           "Unknown — Manual Review",
        "Confidence Level":              "Unknown",
        "Manual Review Flag":            "YES",
        "Ambiguity Notes":               reason,
        "Data Source":                   "Not Found",
    }


# ── Shared resolution logic ───────────────────────────────────────────────────
def _name_lookup(name_candidates: list[str]) -> tuple[str | None, str]:
    """Try a list of name candidates against local dict. Returns (generic_key, brand_matched)."""
    for candidate in name_candidates:
        if not candidate:
            continue
        generic_key, brand_matched = lookup_drug(_normalize_text(candidate))
        if generic_key:
            return generic_key, brand_matched
    return None, ""


def _dual_lookup(rxcui: str, name_candidates: list[str]) -> tuple[str | None, str, str]:
    """
    Run both RXCUI and name lookups simultaneously.
    Returns (generic_key, brand_matched, match_note).

    Priority:
      Both agree  → use result, note "RXCUI + name match confirmed"
      RXCUI only  → use RXCUI result, note accordingly
      Name only   → use name result, note accordingly
      Neither     → (None, "", "not found")
    If they disagree → use RXCUI result, flag disagreement for review
    """
    rxcui_key  = lookup_by_rxcui(rxcui) if rxcui else None
    name_key, brand_matched = _name_lookup(name_candidates)

    if rxcui_key and name_key:
        if rxcui_key == name_key:
            return rxcui_key, brand_matched, "RXCUI match + name match confirmed"
        else:
            # Disagree — RXCUI is more precise, use it but flag
            return rxcui_key, "", f"RXCUI match used (name match found different entry: {name_key}) — verify"
    elif rxcui_key:
        return rxcui_key, "", "RXCUI direct match"
    elif name_key:
        return name_key, brand_matched, "Name match (no RXCUI in dictionary)"
    else:
        return None, "", "not found"


def _resolve_drug(code_system: str, med_code: str,
                  name_candidates: list[str],
                  dosage: str, strength_form: str) -> dict:
    """
    Resolve a drug using dual lookup (RXCUI + name match) after calling external API.

    Flow:
      1. Call external API (RxNorm or NDC) → get drug info + RXCUI
      2. Run DUAL lookup: RXCUI index match AND generic name text match
      3. RXCUI match takes priority; name match confirms or flags disagreement
      4. Enrich result with API data (name, brand, class) regardless of match path
      5. Fall back to name-only if API unavailable
    """
    sys_lower = code_system.lower().strip()

    # ── RxNorm path ───────────────────────────────────────────────────────────
    if sys_lower in RXNORM_SYSTEM_NAMES:
        # MedicationsCode for RxNorm is the drug name (e.g. "Metformin") or RXCUI number
        # Try to extract digits as RXCUI, otherwise use as drug name
        rxcui_digits = re.sub(r"\D", "", med_code)

        api_rxcui  = ""
        api        = None
        api_error  = ""

        if rxcui_digits:
            # med_code looks like a number — treat as RXCUI directly
            api = lookup_rxcui(rxcui_digits)
            if api["found"]:
                api_rxcui = rxcui_digits
            else:
                api_error = api.get("error", "")
        else:
            # med_code is a drug name — search RxNorm by name to get RXCUI
            # Use display name candidates for the API lookup name
            pass  # api stays None; fall through to name-only lookup

        # Dual lookup: use RXCUI from API + name candidates
        all_name_candidates = []
        if api and api["found"]:
            all_name_candidates = [api["generic_name"]] + api.get("brand_names", [])
        all_name_candidates += name_candidates

        dict_key, brand_matched, match_note = _dual_lookup(api_rxcui, all_name_candidates)

        if dict_key:
            # Enrich: override brand/class from API if dict entry is missing them
            entry     = DRUG_DICT[dict_key]
            api_brand = (api.get("brand_names", [""])[0] if api and api["found"] else "") or ""
            api_class = (api.get("drug_class", "") if api and api["found"] else "") or ""
            brand_out = brand_matched or api_brand or (entry.get("brand_names") or [""])[0]
            class_out = entry.get("drug_class") or api_class

            # Temporarily patch entry for display (don't mutate DRUG_DICT)
            source   = "RxNorm API + Local Dict"
            result   = _drug_info_from_dict(dict_key, dosage, strength_form, brand_out, source)
            if not result["Drug Class"] and class_out:
                result["Drug Class"] = class_out
            if api_error:
                result["Ambiguity Notes"] = (result.get("Ambiguity Notes", "") +
                                             f" API note: {api_error}").strip()
            return result

        # Not in dict — return API-only info if we have it
        if api and api["found"]:
            brand = api.get("brand_names", [""])[0] if api.get("brand_names") else ""
            return _drug_info_api_only(
                api["generic_name"], brand, api.get("drug_class", ""),
                f"RxNorm API (RXCUI {api_rxcui})", dosage, strength_form,
                data_source="RxNorm API only",
            )

        # API failed — name-only fallback
        name_key, nm_brand, _ = _dual_lookup("", name_candidates)
        if name_key:
            return _drug_info_from_dict(name_key, dosage, strength_form, nm_brand,
                                        "Local Dict (RxNorm offline)")

        return _drug_info_unknown(
            name_candidates[0] if name_candidates else med_code, dosage,
            f"Not found. RxNorm API: {api_error or 'unavailable'}. Not in local dictionary."
        )

    # ── NDC path ─────────────────────────────────────────────────────────────
    if sys_lower in NDC_SYSTEM_NAMES:
        ndc_result = lookup_ndc(med_code)

        if ndc_result["found"]:
            api_rxcui         = ndc_result.get("rxcui", "")   # RXCUI from openFDA openfda section
            generic_from_ndc  = ndc_result["generic_name"]
            brand_from_ndc    = ndc_result["brand_name"]
            class_from_ndc    = ndc_result.get("dosage_form", "")
            strength_from_ndc = strength_form or class_from_ndc

            all_name_candidates = [generic_from_ndc] + name_candidates

            dict_key, brand_matched, match_note = _dual_lookup(api_rxcui, all_name_candidates)

            if dict_key:
                entry     = DRUG_DICT[dict_key]
                brand_out = brand_matched or brand_from_ndc or (entry.get("brand_names") or [""])[0]
                class_out = entry.get("drug_class") or class_from_ndc
                source    = "NDC API + Local Dict"
                result    = _drug_info_from_dict(dict_key, dosage, strength_from_ndc, brand_out, source)
                if not result["Drug Class"] and class_out:
                    result["Drug Class"] = class_out
                return result

            # NDC resolved but not in local dict
            return _drug_info_api_only(
                generic_from_ndc, brand_from_ndc, class_from_ndc,
                f"openFDA NDC API (NDC {med_code})", dosage, strength_from_ndc,
                data_source="NDC API only",
            )

        # NDC API failed — name fallback
        ndc_error = ndc_result.get("error", "not found")
        name_key, nm_brand, _ = _dual_lookup("", name_candidates)
        if name_key:
            return _drug_info_from_dict(name_key, dosage, strength_form, nm_brand,
                                        "Local Dict (NDC offline)")

        return _drug_info_unknown(
            name_candidates[0] if name_candidates else med_code, dosage,
            f"Not found. NDC API: {ndc_error}. Not in local dictionary."
        )

    # ── Text / display-name path (any other code system) ─────────────────────
    name_key, brand_matched, match_note = _dual_lookup("", name_candidates)
    if name_key:
        return _drug_info_from_dict(name_key, dosage, strength_form, brand_matched,
                                    "Local Dict")
    return _drug_info_unknown(
        name_candidates[0] if name_candidates else "", dosage,
        "Medication not recognized. Add to medication_dictionary.json.",
    )


# ═════════════════════════════════════════════════════════════════════════════
# MODE 1: Structured CSV/Excel input
# ═════════════════════════════════════════════════════════════════════════════

STRUCTURED_OUTPUT_COLS = [
    "MedicationsID",
    "DocID",
    "DateOfService",
    "Normalized Generic Name",
    "Brand Name Match",
    "Dosage",
    "Strength / Form",
    "Drug Class",
    "Possible Indication 1",
    "Possible Indication 2",
    "Possible Indication 3",
    "Why Member May Take This Drug",
    "Possible Related Condition 1",
    "Possible Related Condition 2",
    "Possible Related Condition 3",
    "Possible ICD-10-CM Code 1",
    "ICD-10 Description 1",
    "HCC Category (ICD 1)",
    "HCC Model Hierarchy (ICD 1)",
    "HCC Description (ICD 1)",
    "Possible ICD-10-CM Code 2",
    "ICD-10 Description 2",
    "HCC Category (ICD 2)",
    "HCC Model Hierarchy (ICD 2)",
    "HCC Description (ICD 2)",
    "Possible ICD-10-CM Code 3",
    "ICD-10 Description 3",
    "HCC Category (ICD 3)",
    "HCC Model Hierarchy (ICD 3)",
    "HCC Description (ICD 3)",
    "Possible ICD-10-CM Code 4",
    "ICD-10 Description 4",
    "HCC Category (ICD 4)",
    "HCC Model Hierarchy (ICD 4)",
    "HCC Description (ICD 4)",
    "High Value HCC Flag",
    "Confidence Level",
    "Manual Review Flag",
    "Ambiguity Notes",
    "Data Source",
]


def parse_structured_row(row: dict) -> dict:
    """Parse one structured input row. Returns flat dict with STRUCTURED_OUTPUT_COLS."""

    def _safe(key: str) -> str:
        val = row.get(key, "")
        return "" if str(val).lower() in ("nan", "none", "nat", "") else str(val).strip()

    med_id    = _safe("MedicationsID")
    doc_id    = _safe("DocID")
    dos       = _safe("DateOfService")
    med_code  = _safe("MedicationsCode")
    code_sys  = _safe("MedicationsCodeSystemName")
    disp_name = _safe("MedicationsCodeDisplayName")
    disp_view = _safe("MedicationsCodeDisplayNameView")
    dose_qty  = _safe("DoseQuantity")

    dosage        = dose_qty if dose_qty else _extract_dosage(disp_view or disp_name)
    strength_form = _extract_strength_form(disp_view, disp_name)
    name_candidates = [c for c in [disp_name, disp_view] if c]

    drug_info = _resolve_drug(code_sys, med_code, name_candidates, dosage, strength_form)

    output = {
        "MedicationsID":  med_id,
        "DocID":          doc_id,
        "DateOfService":  dos,
        **drug_info,
    }

    for col in STRUCTURED_OUTPUT_COLS:
        if col not in output:
            output[col] = ""

    return {col: output.get(col, "") for col in STRUCTURED_OUTPUT_COLS}


def parse_structured_dataframe(df_in) -> "pd.DataFrame":
    """
    Parse a full structured DataFrame. Validates columns, returns result DataFrame.

    Speed strategy:
      1. Deduplicate by (MedicationsCodeSystemName, MedicationsCode) — in real
         medication files, thousands of rows share the same drug code, so the API
         only needs to be called once per unique code rather than once per row.
      2. Process unique codes in parallel using ThreadPoolExecutor (20 workers) —
         since all work is I/O-bound (HTTP requests), concurrency gives a large speedup.
      3. Map cached results back to every row that shares the same code.

    Example: 8,000 rows × 200 unique RXCUIs → 200 API calls (parallel) instead of
    8,000 sequential calls. Typical speedup: 20-40×.
    """
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # ── Column validation ─────────────────────────────────────────────────────
    col_map = {c.lower().strip(): c for c in df_in.columns}
    rename  = {}
    missing = []
    for req in REQUIRED_INPUT_COLS:
        key = req.lower().strip()
        if key in col_map:
            rename[col_map[key]] = req
        else:
            missing.append(req)

    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df_in.rename(columns=rename)

    # ── Build flat row list (to_dict avoids iterrows float-coercion of ID cols) ─
    _NULL = {"nan", "none", "nat", ""}

    def _s(v) -> str:
        s = str(v).strip()
        return "" if s.lower() in _NULL else s

    rows = [{k: _s(v) for k, v in row.items()} for row in df.to_dict("records")]

    # ── Step 1: Group rows by unique (code_system, med_code) ─────────────────
    def _key(row_dict: dict) -> tuple:
        return (
            row_dict.get("MedicationsCodeSystemName", "").lower().strip(),
            row_dict.get("MedicationsCode", "").strip(),
        )

    key_to_indices: dict[tuple, list[int]] = {}
    for i, row_dict in enumerate(rows):
        key_to_indices.setdefault(_key(row_dict), []).append(i)

    unique_keys = list(key_to_indices.keys())

    # ── Edge case: empty file (only headers) ─────────────────────────────────
    if not unique_keys:
        return pd.DataFrame(columns=STRUCTURED_OUTPUT_COLS)

    # ── Step 2: Resolve each unique code once, in parallel ───────────────────
    def _resolve_key(key: tuple) -> tuple[tuple, dict]:
        sample = rows[key_to_indices[key][0]]
        code_sys   = sample.get("MedicationsCodeSystemName", "")
        med_code   = sample.get("MedicationsCode", "")
        disp_name  = sample.get("MedicationsCodeDisplayName", "")
        disp_view  = sample.get("MedicationsCodeDisplayNameView", "")
        dose_qty   = sample.get("DoseQuantity", "")
        dosage        = dose_qty if dose_qty else _extract_dosage(disp_view or disp_name)
        strength_form = _extract_strength_form(disp_view, disp_name)
        name_candidates = [c for c in [disp_name, disp_view] if c]
        drug_info = _resolve_drug(code_sys, med_code, name_candidates, dosage, strength_form)
        return key, drug_info

    MAX_WORKERS = min(20, len(unique_keys))
    cache: dict[tuple, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_resolve_key, k): k for k in unique_keys}
        for future in as_completed(futures):
            try:
                k, drug_info = future.result()
                cache[k] = drug_info
            except Exception as exc:
                k = futures[future]
                cache[k] = _drug_info_unknown(
                    str(k[1]), "Unknown", f"Processing error: {exc}"
                )

    # ── Step 3: Map cached results back to every row ──────────────────────────
    # Apply row-specific dosage/strength from each individual row so that rows
    # sharing the same drug code but with different doses show their own values.
    output_rows = []
    for row_dict in rows:
        k         = _key(row_dict)
        drug_info = dict(cache[k])   # shallow copy — don't mutate the shared cache entry

        # Per-row dosage / strength override
        dose_qty   = row_dict.get("DoseQuantity", "")
        disp_view  = row_dict.get("MedicationsCodeDisplayNameView", "")
        disp_name  = row_dict.get("MedicationsCodeDisplayName", "")
        row_dosage = dose_qty if dose_qty else _extract_dosage(disp_view or disp_name)
        row_strength = _extract_strength_form(disp_view, disp_name)
        if row_dosage:
            drug_info["Dosage"] = row_dosage
        if row_strength:
            drug_info["Strength / Form"] = row_strength

        output = {
            "MedicationsID":  row_dict.get("MedicationsID", ""),
            "DocID":          row_dict.get("DocID", ""),
            "DateOfService":  row_dict.get("DateOfService", ""),
            **drug_info,
        }
        for col in STRUCTURED_OUTPUT_COLS:
            output.setdefault(col, "")
        output_rows.append({col: output.get(col, "") for col in STRUCTURED_OUTPUT_COLS})

    return pd.DataFrame(output_rows, columns=STRUCTURED_OUTPUT_COLS)


# ═════════════════════════════════════════════════════════════════════════════
# MODE 2: Free-text / paste input
# ═════════════════════════════════════════════════════════════════════════════

FREETEXT_OUTPUT_COLS = [
    "Row Number",
    "Original Input",
    "Normalized Generic Name",
    "Brand Name Match",
    "Dosage",
    "Strength / Form",
    "Drug Class",
    "Possible Indication 1",
    "Possible Indication 2",
    "Possible Indication 3",
    "Why Member May Take This Drug",
    "Possible Related Condition 1",
    "Possible Related Condition 2",
    "Possible Related Condition 3",
    "Possible ICD-10-CM Code 1",
    "ICD-10 Description 1",
    "HCC Category (ICD 1)",
    "HCC Model Hierarchy (ICD 1)",
    "HCC Description (ICD 1)",
    "Possible ICD-10-CM Code 2",
    "ICD-10 Description 2",
    "HCC Category (ICD 2)",
    "HCC Model Hierarchy (ICD 2)",
    "HCC Description (ICD 2)",
    "Possible ICD-10-CM Code 3",
    "ICD-10 Description 3",
    "HCC Category (ICD 3)",
    "HCC Model Hierarchy (ICD 3)",
    "HCC Description (ICD 3)",
    "Possible ICD-10-CM Code 4",
    "ICD-10 Description 4",
    "HCC Category (ICD 4)",
    "HCC Model Hierarchy (ICD 4)",
    "HCC Description (ICD 4)",
    "High Value HCC Flag",
    "Confidence Level",
    "Manual Review Flag",
    "Ambiguity Notes",
    "Data Source",
]


def parse_medication_line(row_num: int, raw_line: str) -> dict:
    """Parse one free-text medication line."""
    original = raw_line.strip()
    if not original:
        info = _drug_info_unknown("", "Unknown", "Blank line")
        output = {"Row Number": row_num, "Original Input": original, **info}
        for col in FREETEXT_OUTPUT_COLS:
            output.setdefault(col, "")
        return {col: output.get(col, "") for col in FREETEXT_OUTPUT_COLS}

    dosage   = _extract_dosage(original)
    rxcui    = extract_rxcui(original)
    name_raw = _extract_drug_name_text(original)

    # For free text: if RXCUI found, treat as RxNorm; otherwise text match
    code_sys  = "rxnorm" if rxcui else ""
    med_code  = rxcui or ""
    candidates = [c for c in [name_raw] if c]

    drug_info = _resolve_drug(code_sys, med_code, candidates, dosage, dosage)

    output = {"Row Number": row_num, "Original Input": original, **drug_info}
    for col in FREETEXT_OUTPUT_COLS:
        output.setdefault(col, "")
    return {col: output.get(col, "") for col in FREETEXT_OUTPUT_COLS}


def parse_medication_list(text: str) -> list[dict]:
    """Parse a multi-line free-text medication list. Handles duplicates."""
    lines   = text.splitlines()
    results = []
    seen: dict[str, int] = {}
    row_num = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        row_num += 1
        norm_key = _normalize_text(stripped)
        result   = parse_medication_line(row_num, stripped)

        if norm_key in seen:
            orig = seen[norm_key]
            note = result.get("Ambiguity Notes", "")
            result["Ambiguity Notes"]  = f"DUPLICATE of row {orig}. " + note if note else f"DUPLICATE of row {orig}."
            result["Manual Review Flag"] = "YES"
        else:
            seen[norm_key] = row_num

        results.append(result)

    return results
