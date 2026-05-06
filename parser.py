"""
parser.py — Medication parsing, lookup, and enrichment pipeline.

Lookup priority per input row:
  MedicationsCodeSystemName = "RxNorm" → RxNorm API (RXCUI) → local dict → HCC
  MedicationsCodeSystemName = "NDC"    → openFDA NDC API     → local dict → HCC
  Anything else                        → text match (MedicationsCodeDisplayName) → local dict → HCC

HCC enrichment runs after ICD codes are resolved (from local dict).
All ICD codes are looked up in the local CMS-HCC v28 crosswalk.

To add drugs:        edit medication_dictionary.json
To add ICD→HCC maps: edit hcc_crosswalk.json
"""

import re
import json
import os

from rxnorm_client import extract_rxcui, lookup_rxcui
from ndc_client    import lookup_ndc, NDC_SYSTEM_NAMES
from hcc_lookup    import lookup_hcc_for_codes, has_high_value_hcc

# ── Load medication dictionary ────────────────────────────────────────────────
_DICT_PATH = os.path.join(os.path.dirname(__file__), "medication_dictionary.json")


def load_dictionary() -> dict:
    with open(_DICT_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


DRUG_DICT = load_dictionary()

BRAND_TO_GENERIC: dict[str, str] = {}
for _g, _e in DRUG_DICT.items():
    for _b in _e.get("brand_names", []):
        BRAND_TO_GENERIC[_b.lower().strip()] = _g

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
def _build_hcc_columns(icd_codes: list[str]) -> dict:
    """
    Look up HCC info for up to 4 ICD codes.
    Returns flat dict of HCC columns (interleaved with ICD slots 1-4).
    """
    hcc_results = lookup_hcc_for_codes(icd_codes)
    high_value  = has_high_value_hcc(icd_codes)
    out = {}

    for i, hcc in enumerate(hcc_results, start=1):
        out[f"HCC Category (ICD {i})"]     = hcc["hcc_category"]
        out[f"HCC Model Hierarchy (ICD {i})"] = hcc["model_hierarchy"]
        out[f"HCC Description (ICD {i})"]  = hcc["hcc_label"]

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

    hcc_cols = _build_hcc_columns(icd_codes)

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
        "HCC Category (ICD 1)":          hcc_cols.get("HCC Category (ICD 1)", ""),
        "HCC Model Hierarchy (ICD 1)":   hcc_cols.get("HCC Model Hierarchy (ICD 1)", ""),
        "HCC Description (ICD 1)":       hcc_cols.get("HCC Description (ICD 1)", ""),
        "Possible ICD-10-CM Code 2":     icd_codes[1],
        "HCC Category (ICD 2)":          hcc_cols.get("HCC Category (ICD 2)", ""),
        "HCC Model Hierarchy (ICD 2)":   hcc_cols.get("HCC Model Hierarchy (ICD 2)", ""),
        "HCC Description (ICD 2)":       hcc_cols.get("HCC Description (ICD 2)", ""),
        "Possible ICD-10-CM Code 3":     icd_codes[2],
        "HCC Category (ICD 3)":          hcc_cols.get("HCC Category (ICD 3)", ""),
        "HCC Model Hierarchy (ICD 3)":   hcc_cols.get("HCC Model Hierarchy (ICD 3)", ""),
        "HCC Description (ICD 3)":       hcc_cols.get("HCC Description (ICD 3)", ""),
        "Possible ICD-10-CM Code 4":     icd_codes[3],
        "HCC Category (ICD 4)":          hcc_cols.get("HCC Category (ICD 4)", ""),
        "HCC Model Hierarchy (ICD 4)":   hcc_cols.get("HCC Model Hierarchy (ICD 4)", ""),
        "HCC Description (ICD 4)":       hcc_cols.get("HCC Description (ICD 4)", ""),
        "High Value HCC Flag":           hcc_cols.get("High Value HCC Flag", "No"),
        "Confidence Level":              entry.get("confidence", ""),
        "Manual Review Flag":            "YES" if entry.get("manual_review") else "No",
        "Ambiguity Notes":               entry.get("ambiguity_note", ""),
        "Data Source":                   data_source,
    }


def _drug_info_api_only(api_name: str, api_brand: str, api_class: str,
                        api_ref: str, dosage: str, strength_form: str,
                        data_source: str) -> dict:
    """Drug resolved via API (RxNorm or NDC) but not in local dict — ICD/HCC unavailable."""
    empty_hcc = {
        f"HCC Category (ICD {i})": "" for i in range(1, 5)
    } | {
        f"HCC Model Hierarchy (ICD {i})": "" for i in range(1, 5)
    } | {
        f"HCC Description (ICD {i})": "" for i in range(1, 5)
    }

    return {
        "Normalized Generic Name":       api_name.title() if api_name else "",
        "Brand Name Match":              api_brand.title() if api_brand else "",
        "Dosage":                        dosage,
        "Strength / Form":               strength_form or dosage,
        "Drug Class":                    api_class,
        "Possible Indication 1":         "Insufficient specificity — not in local dictionary",
        "Possible Indication 2":         "",
        "Possible Indication 3":         "",
        "Why Member May Take This Drug": (
            f"Drug identified via {api_ref}. "
            "Not yet mapped in medication_dictionary.json — add entry for full ICD and HCC mapping."
        ),
        "Possible Related Condition 1":  "Manual review required",
        "Possible Related Condition 2":  "",
        "Possible Related Condition 3":  "",
        "Possible ICD-10-CM Code 1":     "N/A — not in local dictionary",
        **empty_hcc,
        "Possible ICD-10-CM Code 2":     "",
        "Possible ICD-10-CM Code 3":     "",
        "Possible ICD-10-CM Code 4":     "",
        "High Value HCC Flag":           "Unknown — Manual Review",
        "Confidence Level":              "Low",
        "Manual Review Flag":            "YES",
        "Ambiguity Notes":               f"Resolved via {api_ref}. ICD-10/HCC mapping unavailable — add to medication_dictionary.json.",
        "Data Source":                   data_source,
    }


def _drug_info_unknown(parsed_name: str, dosage: str, reason: str) -> dict:
    empty_hcc = {
        f"HCC Category (ICD {i})": "" for i in range(1, 5)
    } | {
        f"HCC Model Hierarchy (ICD {i})": "" for i in range(1, 5)
    } | {
        f"HCC Description (ICD {i})": "" for i in range(1, 5)
    }
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
        **empty_hcc,
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
def _try_local_dict(name_candidates: list[str], dosage: str, strength_form: str,
                    data_source: str) -> dict | None:
    """Try name candidates against local dict. Returns drug info dict or None."""
    for candidate in name_candidates:
        if not candidate:
            continue
        norm = _normalize_text(candidate)
        generic_key, brand_matched = lookup_drug(norm)
        if generic_key:
            return _drug_info_from_dict(generic_key, dosage, strength_form, brand_matched, data_source)
    return None


def _resolve_drug(code_system: str, med_code: str,
                  name_candidates: list[str],
                  dosage: str, strength_form: str) -> dict:
    """
    Resolve a drug to its full info dict using the appropriate lookup path.

    MedicationsCodeSystemName = RxNorm → RxNorm API → local dict → HCC
    MedicationsCodeSystemName = NDC    → openFDA NDC API → local dict → HCC
    Anything else                      → local dict text match → HCC
    """
    sys_lower = code_system.lower().strip()

    # ── RxNorm path ───────────────────────────────────────────────────────────
    if sys_lower in RXNORM_SYSTEM_NAMES:
        rxcui = re.sub(r"\D", "", med_code)
        if rxcui:
            api = lookup_rxcui(rxcui)
            if api["found"]:
                # Try local dict with generic and brand names from API
                for name in [api["generic_name"]] + api["brand_names"]:
                    generic_key, brand_matched = lookup_drug(name)
                    if generic_key:
                        return _drug_info_from_dict(
                            generic_key, dosage, strength_form, brand_matched,
                            data_source=f"RxNorm API + Local Dictionary (RXCUI {rxcui})",
                        )
                # API found drug but not in local dict
                brand = api["brand_names"][0] if api["brand_names"] else ""
                return _drug_info_api_only(
                    api["generic_name"], brand, api.get("drug_class", ""),
                    f"RxNorm API (RXCUI {rxcui})", dosage, strength_form,
                    data_source=f"RxNorm API only (RXCUI {rxcui}) — add to local dict for ICD/HCC",
                )
            # API failed — fall through to text lookup
            api_error_note = f" (RxNorm API failed: {api.get('error', '')})"
        else:
            api_error_note = " (invalid RXCUI)"

        result = _try_local_dict(name_candidates, dosage, strength_form,
                                 "Local Dictionary" + api_error_note)
        if result:
            return result
        return _drug_info_unknown(
            name_candidates[0] if name_candidates else med_code, dosage,
            f"RxNorm lookup failed{api_error_note}. Medication not in local dictionary."
        )

    # ── NDC path ─────────────────────────────────────────────────────────────
    if sys_lower in NDC_SYSTEM_NAMES:
        ndc_result = lookup_ndc(med_code)
        if ndc_result["found"]:
            generic_from_ndc  = ndc_result["generic_name"]
            brand_from_ndc    = ndc_result["brand_name"]
            class_from_ndc    = ndc_result["dosage_form"]   # best proxy available
            strength_from_ndc = strength_form or ndc_result.get("dosage_form", "")

            # Build richer name candidates: NDC generic + display names
            all_candidates = [generic_from_ndc] + name_candidates
            result = _try_local_dict(all_candidates, dosage, strength_from_ndc,
                                     f"NDC API + Local Dictionary (NDC {med_code})")
            if result:
                return result

            # NDC resolved but not in local dict
            return _drug_info_api_only(
                generic_from_ndc, brand_from_ndc, class_from_ndc,
                f"openFDA NDC API (NDC {med_code})",
                dosage, strength_from_ndc,
                data_source=f"openFDA NDC API (NDC {med_code}) — add to local dict for ICD/HCC",
            )

        # NDC API failed — fall through to display name text lookup
        ndc_error_note = f" (NDC API: {ndc_result.get('error', 'not found')})"
        result = _try_local_dict(name_candidates, dosage, strength_form,
                                 "Local Dictionary" + ndc_error_note)
        if result:
            return result
        return _drug_info_unknown(
            name_candidates[0] if name_candidates else med_code, dosage,
            f"NDC lookup failed{ndc_error_note}. Medication not in local dictionary."
        )

    # ── Text / display-name path (any other code system) ─────────────────────
    result = _try_local_dict(name_candidates, dosage, strength_form, "Local Dictionary")
    if result:
        return result
    return _drug_info_unknown(
        name_candidates[0] if name_candidates else "", dosage,
        "Medication not recognized in local dictionary. Add entry to medication_dictionary.json.",
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
    "HCC Category (ICD 1)",
    "HCC Model Hierarchy (ICD 1)",
    "HCC Description (ICD 1)",
    "Possible ICD-10-CM Code 2",
    "HCC Category (ICD 2)",
    "HCC Model Hierarchy (ICD 2)",
    "HCC Description (ICD 2)",
    "Possible ICD-10-CM Code 3",
    "HCC Category (ICD 3)",
    "HCC Model Hierarchy (ICD 3)",
    "HCC Description (ICD 3)",
    "Possible ICD-10-CM Code 4",
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
    """Parse a full structured DataFrame. Validates columns, returns result DataFrame."""
    import pandas as pd

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
    results = [parse_structured_row(row) for _, row in df.iterrows()]
    return pd.DataFrame(results, columns=STRUCTURED_OUTPUT_COLS)


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
    "HCC Category (ICD 1)",
    "HCC Model Hierarchy (ICD 1)",
    "HCC Description (ICD 1)",
    "Possible ICD-10-CM Code 2",
    "HCC Category (ICD 2)",
    "HCC Model Hierarchy (ICD 2)",
    "HCC Description (ICD 2)",
    "Possible ICD-10-CM Code 3",
    "HCC Category (ICD 3)",
    "HCC Model Hierarchy (ICD 3)",
    "HCC Description (ICD 3)",
    "Possible ICD-10-CM Code 4",
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
