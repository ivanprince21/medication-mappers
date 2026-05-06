"""
build_dictionary.py
===================
One-time script: builds medication_dictionary.json from the MEDI-C.csv dataset.

What it does:
  1. Reads MEDI-C.csv (MEDI dataset — drug-to-ICD indication mappings)
  2. Filters to ICD-10-CM rows only (drops ICD-9)
  3. Groups by drug (RXCUI + generic name)
  4. Selects top 4 ICD codes per drug ranked by confidence:
       MEDI2_HPS=TRUE (highest) > MEDI1_HPS=TRUE > MEDI2=TRUE > MEDI1=TRUE
  5. Keeps the existing 27 hand-curated drugs untouched
  6. Adds all new drugs from MEDI to medication_dictionary.json

Usage (run once from the medication_mapper folder):
  python build_dictionary.py "C:\\Users\\IvanP\\Downloads\\MEDI-C.csv"

Optional — limit how many new drugs to add (good for testing):
  python build_dictionary.py "C:\\Users\\IvanP\\Downloads\\MEDI-C.csv" --limit 100

After running, restart the app:
  streamlit run app.py
"""

import csv
import json
import os
import re
import sys
import argparse
from collections import defaultdict

# ── Paths ─────────────────────────────────────────────────────────────────────
DICT_PATH = os.path.join(os.path.dirname(__file__), "medication_dictionary.json")


# ── Helpers ───────────────────────────────────────────────────────────────────
def is_valid_icd10(code: str) -> bool:
    """
    Accept only specific ICD-10-CM codes.
    Reject: ranges (e.g. E08-E13), ICD-9 codes, blank codes.
    """
    code = code.strip()
    if not code or "-" in code or len(code) > 8:
        return False
    return bool(re.match(r"^[A-Z]\d{2}", code))


def confidence_score(row: dict) -> int:
    """Rank a single indication row by MEDI confidence flags (higher = better)."""
    if row.get("MEDI2_HPS", "").upper() == "TRUE":
        return 4
    if row.get("MEDI1_HPS", "").upper() == "TRUE":
        return 3
    if row.get("MEDI2", "").upper() == "TRUE":
        return 2
    if row.get("MEDI1", "").upper() == "TRUE":
        return 1
    return 0


def overall_confidence(rows: list[dict]) -> str:
    """
    Determine overall Confidence Level label for a drug from its indication rows.
    High  = at least one MEDI2_HPS=TRUE row
    Medium = at least one MEDI2=TRUE but no MEDI2_HPS
    Low   = only MEDI1 flags
    """
    if any(r.get("MEDI2_HPS", "").upper() == "TRUE" for r in rows):
        return "High"
    if any(r.get("MEDI2", "").upper() == "TRUE" for r in rows):
        return "Medium"
    return "Low"


def clean_desc(desc: str) -> str:
    """Clean up indication description text."""
    desc = desc.strip()
    # Remove trailing ICD-style suffixes in parentheses
    desc = re.sub(r"\s*\(.*?\)\s*$", "", desc)
    # Collapse whitespace
    desc = re.sub(r"\s+", " ", desc)
    return desc


def generate_why_takes(indications: list[str], drug_name: str) -> str:
    """Auto-generate plain-language 'why member may take this drug' text."""
    if not indications:
        return f"Possible use for conditions associated with {drug_name}. Review clinical context."
    if len(indications) == 1:
        return f"Most commonly used for {indications[0].lower()}."
    if len(indications) == 2:
        return (
            f"Used for {indications[0].lower()} and {indications[1].lower()}. "
            "Verify specific indication with clinical context."
        )
    return (
        f"Used for {indications[0].lower()}, {indications[1].lower()}, and other related conditions. "
        "Cannot determine specific use from drug name alone — manual review recommended."
    )


def generate_ambiguity_note(n_icd_codes: int, drug_name: str, confidence: str) -> str:
    """Auto-generate ambiguity note based on breadth of indications."""
    if n_icd_codes > 20:
        return (
            f"{drug_name.title()} has a broad indication profile "
            f"({n_icd_codes} ICD-10 codes mapped in MEDI dataset). "
            "Cannot determine specific use from drug name alone. Manual review required."
        )
    if n_icd_codes > 8:
        return (
            f"Multiple possible indications ({n_icd_codes} ICD-10 codes). "
            "Review clinical context to determine primary use."
        )
    if confidence == "Low":
        return (
            "Low confidence mapping — indication derived from broad association only. "
            "Manual review recommended."
        )
    if confidence == "Medium":
        return (
            f"Medium confidence — {n_icd_codes} ICD-10 code(s) mapped. "
            "Confirm specific indication with clinical notes."
        )
    return ""


def build_entry(rxcui: str, drug_name: str, icd10_rows: list[dict]) -> dict | None:
    """
    Build one medication dictionary entry from a drug's ICD-10-CM indication rows.
    Returns None if no valid specific ICD codes found.
    """
    # Sort all rows by confidence descending
    sorted_rows = sorted(icd10_rows, key=confidence_score, reverse=True)

    # Keep only rows with valid specific ICD-10 codes
    valid_rows = [r for r in sorted_rows if is_valid_icd10(r.get("CODE", ""))]
    if not valid_rows:
        return None

    # Select top 4 unique ICD codes
    seen_codes: set[str] = set()
    top_icd_rows: list[dict] = []
    for r in valid_rows:
        code = r["CODE"].strip()
        if code not in seen_codes:
            seen_codes.add(code)
            top_icd_rows.append(r)
        if len(top_icd_rows) >= 4:
            break

    icd_codes = [r["CODE"].strip() for r in top_icd_rows]

    # Build indications list (top 3 unique, readable descriptions)
    seen_descs: set[str] = set()
    indications: list[str] = []
    for r in valid_rows:
        desc = clean_desc(r.get("INDICATION_DESC", ""))
        if desc and desc.lower() not in seen_descs and len(desc) < 90:
            seen_descs.add(desc.lower())
            indications.append(desc)
        if len(indications) >= 3:
            break

    confidence  = overall_confidence(valid_rows)
    n_total_icd = len(set(r["CODE"].strip() for r in valid_rows if is_valid_icd10(r.get("CODE", ""))))
    manual_rev  = confidence in ("Low", "Medium") or n_total_icd > 8

    return {
        "generic_name":    drug_name,
        "rxcui":           rxcui,          # stored for faster RXCUI-based lookup
        "brand_names":     [],             # fetched at runtime from RxNorm API via RXCUI
        "drug_class":      "",             # fetched at runtime from RxNorm API via RXCUI
        "indications":     indications,
        "why_member_takes": generate_why_takes(indications, drug_name),
        "related_conditions": indications[:3],
        "icd10_codes":     icd_codes,
        "confidence":      confidence,
        "manual_review":   manual_rev,
        "ambiguity_note":  generate_ambiguity_note(n_total_icd, drug_name, confidence),
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Build medication_dictionary.json from MEDI-C.csv")
    parser.add_argument("csv_path", help="Path to MEDI-C.csv")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max new drugs to add (0 = no limit, default). Use for testing.")
    args = parser.parse_args()

    csv_path = args.csv_path

    if not os.path.exists(csv_path):
        print(f"\nERROR: File not found: {csv_path}")
        sys.exit(1)

    # ── Step 1: Load existing dictionary ─────────────────────────────────────
    print("\n[1/4] Loading existing medication_dictionary.json ...")
    with open(DICT_PATH, "r", encoding="utf-8") as f:
        existing_dict = json.load(f)

    existing_generics = {k for k in existing_dict if not k.startswith("_")}
    print(f"      Existing hand-curated drugs: {len(existing_generics)}")
    print(f"      These will NOT be overwritten: {sorted(existing_generics)}")

    # ── Step 2: Read and parse MEDI CSV ──────────────────────────────────────
    print(f"\n[2/4] Reading MEDI-C.csv ...")
    drug_rows: dict[str, list[dict]]  = defaultdict(list)  # rxcui → rows
    drug_names: dict[str, str]        = {}                  # rxcui → generic name
    total_rows = skipped_icd9 = skipped_no_conf = 0

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1

            # Print progress every 50k rows
            if total_rows % 50000 == 0:
                print(f"      ... {total_rows:,} rows read")

            if row.get("SAB", "") != "ICD10CM":
                skipped_icd9 += 1
                continue

            if confidence_score(row) == 0:
                skipped_no_conf += 1
                continue

            rxcui     = row["RXCUI"].strip()
            drug_name = row["DRUG_DESC"].strip().lower()
            drug_rows[rxcui].append(row)
            drug_names[rxcui] = drug_name

    print(f"      Total rows read:           {total_rows:,}")
    print(f"      ICD-9 rows skipped:        {skipped_icd9:,}")
    print(f"      Zero-confidence skipped:   {skipped_no_conf:,}")
    print(f"      Unique drugs (ICD-10-CM):  {len(drug_rows):,}")

    # ── Step 3: Build new entries ─────────────────────────────────────────────
    print(f"\n[3/4] Building dictionary entries ...")
    new_entries: dict[str, dict] = {}
    kept_existing = added = skipped_no_icd = 0

    for rxcui, rows in drug_rows.items():
        drug_name = drug_names[rxcui]

        # Existing 27 drugs take priority — skip if already mapped
        if drug_name in existing_generics:
            kept_existing += 1
            continue

        # Also skip if already added (duplicate name, different RXCUI)
        if drug_name in new_entries:
            continue

        entry = build_entry(rxcui, drug_name, rows)
        if entry:
            new_entries[drug_name] = entry
            added += 1
        else:
            skipped_no_icd += 1

        # Respect optional limit
        if args.limit and added >= args.limit:
            print(f"      --limit {args.limit} reached — stopping early.")
            break

    print(f"      Existing drugs preserved:  {kept_existing}")
    print(f"      New drugs to add:          {added:,}")
    print(f"      Skipped (no valid ICD-10): {skipped_no_icd:,}")

    # ── Step 4: Merge and save ────────────────────────────────────────────────
    print(f"\n[4/4] Merging and saving medication_dictionary.json ...")
    merged = dict(existing_dict)   # start with everything (includes _INSTRUCTIONS key)
    merged.update(new_entries)     # add new drugs

    with open(DICT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    total_drugs = len([k for k in merged if not k.startswith("_")])

    print(f"\n{'='*60}")
    print(f"  DONE.")
    print(f"  medication_dictionary.json updated.")
    print(f"  Total drugs in dictionary: {total_drugs:,}")
    print(f"  Original 27 drugs:         preserved (not overwritten)")
    print(f"  New drugs added from MEDI: {added:,}")
    print(f"{'='*60}")
    print(f"\nNext step — restart the app:")
    print(f"  streamlit run app.py\n")


if __name__ == "__main__":
    main()
