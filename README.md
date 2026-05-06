# Medication Indication Mapper

Local research/support tool for mapping medication lists to possible indications and possible ICD-10-CM codes.

> **DISCLAIMER:** This tool provides *possible* medication indications and *possible* related ICD-10-CM codes for research/support use only. It does **not** diagnose, confirm a condition, or replace clinical judgment. All outputs are possible indications only — not confirmed diagnoses or final billing codes.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
streamlit run app.py
```

App opens automatically at `http://localhost:8501`

---

## Features

- Upload `.txt` or `.csv` medication lists, or paste directly
- Parses drug name + dosage from messy input
- Normalizes brand names to generic names
- Returns structured columns — one medication per row
- Summary metrics: total, recognized, unknown, manual review count
- Filter by drug name, confidence level, review flag
- Export to Excel (`.xlsx`) with frozen header row
- Export to tab-delimited text (`.txt`)

## Output Columns

| Column | Description |
|--------|-------------|
| Row Number | Input line number |
| Original Input | Verbatim input line |
| Parsed Drug Name | Extracted drug name (title case) |
| Normalized Generic Name | Mapped generic name |
| Brand Name Match | Brand name if matched |
| Dosage | Extracted dosage string |
| Strength / Form | Same as dosage (extend parser.py for form parsing) |
| Drug Class | Pharmacological class |
| Possible Indication 1–3 | Possible uses (labeled as possible only) |
| Why Member May Take This Drug | Plain-language explanation |
| Possible Related Condition 1–3 | Possible associated conditions |
| Possible ICD-10-CM Code 1–3 | Possible codes (not confirmed billing codes) |
| Confidence Level | High / Medium / Low / Unknown |
| Manual Review Flag | YES = requires human review |
| Ambiguity Notes | Reason for uncertainty |

---

## How to Edit Medication Data

Open `medication_dictionary.json`. Each drug entry looks like:

```json
"metformin": {
  "generic_name": "metformin",
  "brand_names": ["glucophage", "glucophage xr"],
  "drug_class": "Biguanide / Antidiabetic",
  "indications": ["Type 2 diabetes mellitus", "Prediabetes", "PCOS (off-label)"],
  "why_member_takes": "Used to control blood sugar in type 2 diabetes.",
  "related_conditions": ["Type 2 diabetes mellitus", "Polycystic ovary syndrome", "Insulin resistance"],
  "icd10_codes": ["E11.9", "E28.2", "R73.09"],
  "confidence": "High",
  "manual_review": false,
  "ambiguity_note": "Primarily type 2 DM."
}
```

**To add a new drug:**
1. Open `medication_dictionary.json`
2. Copy any existing entry as a template
3. Add your new entry with a lowercase generic name as the key
4. Add brand names in the `brand_names` list (all lowercase)
5. Save — the app reloads the dictionary on each run

**To modify matching logic:**
- See `parser.py` → `lookup_drug()` for matching priority
- See `parser.py` → `parse_medication_line()` for column assembly

---

## Included Drugs (25+)

metformin, lisinopril, atorvastatin, gabapentin, prednisone, omeprazole, amlodipine, levothyroxine, sertraline, metoprolol, albuterol, furosemide, pantoprazole, hydrochlorothiazide, simvastatin, losartan, warfarin, alprazolam, amoxicillin, citalopram, duloxetine, insulin glargine, rosuvastatin, tramadol, montelukast, clopidogrel, cyclobenzaprine

---

## Project Files

```
medication_mapper/
├── app.py                      ← Streamlit UI and export logic
├── parser.py                   ← Input parsing and drug lookup
├── medication_dictionary.json  ← Drug mapping data (edit this)
├── requirements.txt
└── README.md
```
