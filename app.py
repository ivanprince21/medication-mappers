"""
Medication Indication Mapper
============================
Local Streamlit app. Two input modes:
  Tab 1 — Structured CSV/Excel with required columns  ← Primary
  Tab 2 — Free-text paste / upload                    ← Quick test

Lookup routing:
  MedicationsCodeSystemName = RxNorm → NLM RxNorm API (RXCUI)
  MedicationsCodeSystemName = NDC    → openFDA NDC API
  Anything else                      → local dictionary (display name text match)

After ICD codes resolved: HCC enrichment via local CMS-HCC v28 crosswalk.

Run: streamlit run app.py
"""

import io
import pandas as pd
import streamlit as st

from parser import (
    parse_structured_dataframe,
    parse_medication_list,
    REQUIRED_INPUT_COLS,
    STRUCTURED_OUTPUT_COLS,
)
from rxnorm_client import check_api_available
from ndc_client    import check_ndc_api_available
from icd10_client  import lookup_description as _icd10_ping

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Medication Indication Mapper",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .main-header  { font-size:2rem; font-weight:700; color:#1a3c5e; margin-bottom:0.2rem; }
    .sub-header   { font-size:1rem; color:#4a6fa5; margin-bottom:1rem; }
    .disclaimer-box {
        background:#fff3cd; border-left:5px solid #ffc107;
        padding:0.75rem 1rem; border-radius:4px;
        font-size:0.9rem; color:#856404; margin-bottom:1rem;
    }
    .api-online  { color:#155724; background:#d4edda; padding:3px 10px; border-radius:4px; font-size:0.82rem; }
    .api-offline { color:#721c24; background:#f8d7da; padding:3px 10px; border-radius:4px; font-size:0.82rem; }
    .hcc-flag    { color:#856404; background:#fff3cd; padding:3px 8px; border-radius:4px; font-size:0.82rem; font-weight:600; }
    .section-label { font-weight:600; color:#1a3c5e; margin-top:1rem; }
    .req-cols { font-family:monospace; font-size:0.82rem; background:#f0f4f8; padding:0.5rem 1rem; border-radius:4px; }
    div[data-testid="stDataFrame"] { font-size:0.82rem; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="main-header">💊 Medication Indication Mapper</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Research / Support Review Tool — Local Use Only</div>', unsafe_allow_html=True)

st.markdown("""
<div class="disclaimer-box">
    ⚠️ <strong>Disclaimer:</strong> This tool provides <strong>possible</strong> medication indications,
    <strong>possible</strong> related ICD-10-CM codes, and <strong>possible</strong> HCC categories
    for research/support use only. It does <strong>not</strong> diagnose, confirm a condition,
    confirm an HCC assignment, or replace clinical judgment.
    All outputs are possible indications only — not confirmed diagnoses or final billing codes.
</div>
""", unsafe_allow_html=True)

# ── API status row ────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def get_api_status():
    icd10_ok = bool(_icd10_ping("E11.9"))
    return check_api_available(), check_ndc_api_available(), icd10_ok

rxnorm_ok, ndc_ok, icd10_ok = get_api_status()

sc1, sc2, sc3, sc4 = st.columns([2, 2, 2, 3])
with sc1:
    icon = "🟢" if rxnorm_ok else "🔴"
    cls  = "api-online" if rxnorm_ok else "api-offline"
    txt  = "Online" if rxnorm_ok else "Offline"
    st.markdown(f'{icon} <span class="{cls}">RxNorm API: {txt}</span>', unsafe_allow_html=True)
with sc2:
    icon = "🟢" if ndc_ok else "🔴"
    cls  = "api-online" if ndc_ok else "api-offline"
    txt  = "Online" if ndc_ok else "Offline"
    st.markdown(f'{icon} <span class="{cls}">openFDA NDC API: {txt}</span>', unsafe_allow_html=True)
with sc3:
    icon = "🟢" if icd10_ok else "🔴"
    cls  = "api-online" if icd10_ok else "api-offline"
    txt  = "Online" if icd10_ok else "Offline"
    st.markdown(f'{icon} <span class="{cls}">ICD-10 NLM API: {txt}</span>', unsafe_allow_html=True)
with sc4:
    st.markdown('<span class="hcc-flag">🏷 HCC: CMS-HCC v28 crosswalk (local — offline capable)</span>',
                unsafe_allow_html=True)

st.markdown("")

# ═════════════════════════════════════════════════════════════════════════════
# INPUT TABS
# ═════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Step 1 — Input Medication Data</div>', unsafe_allow_html=True)

tab_struct, tab_text = st.tabs([
    "📋 Structured File Upload (CSV / Excel)  ← Primary",
    "✏️  Free Text / Paste  ← Quick Test",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Structured File
# ─────────────────────────────────────────────────────────────────────────────
with tab_struct:

    st.markdown("**Required columns** (exact names, case-insensitive):")
    st.markdown(
        '<div class="req-cols">' + " &nbsp;|&nbsp; ".join(REQUIRED_INPUT_COLS) + "</div>",
        unsafe_allow_html=True
    )

    with st.expander("📌 How lookup routing works"):
        st.markdown("""
| `MedicationsCodeSystemName` value | Lookup used |
|---|---|
| `RxNorm`, `rxnorm`, `RXN`, `rxnorm code` | **NLM RxNorm API** — `MedicationsCode` treated as RXCUI |
| `NDC`, `ndc`, `National Drug Code`, `ndc11`, `ndc10` | **openFDA NDC API** — `MedicationsCode` treated as NDC |
| Anything else | **Local dictionary** — text match on `MedicationsCodeDisplayName` |

After ICD codes are resolved from the local dictionary, each code is:
1. Looked up in the **NLM ICD-10-CM API** for a full description (requires internet)
2. Looked up in the **CMS-HCC Model v28 crosswalk** (bundled locally — works offline)

For drugs not in the local dictionary (API-only), a **live ICD-10 search** is attempted using the drug class.
        """)

    struct_file = st.file_uploader(
        "Upload CSV or Excel file",
        type=["csv", "xlsx", "xls"],
        key="struct_upload",
    )

    df_input = None

    if struct_file:
        try:
            ext = struct_file.name.rsplit(".", 1)[-1].lower()
            df_input = pd.read_csv(struct_file, dtype=str) if ext == "csv" else pd.read_excel(struct_file, dtype=str)

            st.success(f"Loaded: **{struct_file.name}** — {len(df_input):,} rows, {len(df_input.columns)} columns")

            input_cols_lower = {c.lower().strip() for c in df_input.columns}
            missing_cols     = [c for c in REQUIRED_INPUT_COLS if c.lower().strip() not in input_cols_lower]
            extra_cols       = [c for c in df_input.columns if c.lower().strip() not in {r.lower() for r in REQUIRED_INPUT_COLS}]

            if missing_cols:
                st.error(f"Missing required columns: **{missing_cols}**")
                st.stop()
            else:
                st.success("All required columns found.")
            if extra_cols:
                st.info(f"Extra columns (ignored): {extra_cols}")

            with st.expander("Preview first 10 rows"):
                st.dataframe(df_input.head(10), use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Could not read file: {e}")
            df_input = None

    st.markdown('<div class="section-label">Step 2 — Process</div>', unsafe_allow_html=True)
    run_struct = st.button(
        "🔍 Parse / Process Structured File",
        type="primary",
        key="run_struct",
        disabled=(df_input is None),
    )

    if run_struct and df_input is not None:
        try:
            with st.spinner(f"Processing {len(df_input):,} rows — RxNorm/NDC rows query external APIs..."):
                result_df = parse_structured_dataframe(df_input)
            st.session_state["results_df"]   = result_df
            st.session_state["results_mode"] = "structured"
            st.success(f"Done — {len(result_df):,} rows processed.")
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Processing error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — Free Text
# ─────────────────────────────────────────────────────────────────────────────
SAMPLE_FREE_TEXT = """\
Metformin 500 mg
Lisinopril 10 mg
Atorvastatin 40 mg
Gabapentin 300 mg
Prednisone 10 mg
Warfarin 5 mg
RXCUI:860975
310798
UnknownDrugXYZ 100 mg
"""

with tab_text:
    with st.expander("ℹ️ Supported free-text formats"):
        st.markdown("""
```
Metformin 500 mg              ← drug name + dose (local dict)
Lipitor 40mg                  ← brand name (local dict)
RXCUI:860975                  ← RxNorm RXCUI (API lookup)
860975                        ← bare RXCUI number
Atorvastatin 40mg RXCUI:83367 ← name + RXCUI (RXCUI takes priority)
```
HCC enrichment runs on all resolved ICD codes automatically.
        """)

    raw_text = ""
    ft_file  = st.file_uploader("Upload .txt or .csv", type=["txt", "csv"], key="ft_upload")
    if ft_file:
        try:
            raw_text = ft_file.read().decode("utf-8", errors="replace")
            st.success(f"Loaded: {ft_file.name} ({len(raw_text.splitlines())} lines)")
        except Exception as e:
            st.error(f"Could not read file: {e}")

    col_area, col_btn = st.columns([5, 1])
    with col_btn:
        if st.button("Load Sample", use_container_width=True, key="load_sample"):
            st.session_state["ft_paste"] = SAMPLE_FREE_TEXT
    with col_area:
        pasted = st.text_area(
            "Or paste medication list (one per line):",
            value=st.session_state.get("ft_paste", ""),
            height=200,
            key="ft_paste_area",
            placeholder="Metformin 500 mg\nRXCUI:860975\n...",
        )
    if pasted.strip():
        raw_text = pasted

    st.markdown('<div class="section-label">Step 2 — Process</div>', unsafe_allow_html=True)
    run_free = st.button("🔍 Parse / Process Free Text", type="primary", key="run_free")

    if run_free:
        if not raw_text or not raw_text.strip():
            st.error("No input provided.")
        else:
            with st.spinner("Parsing..."):
                try:
                    results = parse_medication_list(raw_text)
                    if not results:
                        st.warning("No medication lines found.")
                    else:
                        st.session_state["results_df"]   = pd.DataFrame(results)
                        st.session_state["results_mode"] = "freetext"
                except Exception as e:
                    st.error(f"Parsing error: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# RESULTS
# ═════════════════════════════════════════════════════════════════════════════
if "results_df" in st.session_state:
    df: pd.DataFrame = st.session_state["results_df"]
    mode: str        = st.session_state.get("results_mode", "freetext")

    st.markdown("---")
    st.markdown('<div class="section-label">Results</div>', unsafe_allow_html=True)

    # ── Summary metrics ───────────────────────────────────────────────────────
    total        = len(df)
    unknown_mask = df["Normalized Generic Name"].isin(["Unknown Medication", "Unknown"])
    recognized   = int((~unknown_mask).sum())
    unknown      = int(unknown_mask.sum())
    need_review  = int((df["Manual Review Flag"] == "YES").sum())
    high_hcc     = int(df["High Value HCC Flag"].str.startswith("YES").sum()) if "High Value HCC Flag" in df.columns else 0
    api_rows     = int(df["Data Source"].str.contains("API", na=False).sum()) if "Data Source" in df.columns else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Rows",         total)
    c2.metric("Recognized",         recognized)
    c3.metric("Unknown",            unknown)
    c4.metric("Manual Review",      need_review)
    c5.metric("High Value HCC",     high_hcc)
    c6.metric("Via External API",   api_rows)

    # ── Filters ───────────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Filter Results</div>', unsafe_allow_html=True)
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)

    with fc1:
        search = st.text_input("Search:", placeholder="drug, ICD, HCC, condition...")
    with fc2:
        f_review = st.selectbox("Manual Review:", ["All", "YES", "No"])
    with fc3:
        f_conf = st.selectbox("Confidence:", ["All", "High", "Medium", "Low", "Unknown"])
    with fc4:
        f_hcc = st.selectbox("High Value HCC:", ["All", "YES — Review", "No", "Unknown — Manual Review"])
    with fc5:
        src_opts = ["All"] + sorted(df["Data Source"].dropna().unique().tolist()) if "Data Source" in df.columns else ["All"]
        f_src = st.selectbox("Data Source:", src_opts)

    display_df = df.copy()
    if search:
        mask = display_df.apply(lambda r: r.astype(str).str.contains(search, case=False).any(), axis=1)
        display_df = display_df[mask]
    if f_review != "All":
        display_df = display_df[display_df["Manual Review Flag"] == f_review]
    if f_conf != "All":
        display_df = display_df[display_df["Confidence Level"] == f_conf]
    if f_hcc != "All" and "High Value HCC Flag" in display_df.columns:
        display_df = display_df[display_df["High Value HCC Flag"] == f_hcc]
    if f_src != "All" and "Data Source" in display_df.columns:
        display_df = display_df[display_df["Data Source"] == f_src]

    st.caption(f"Showing {len(display_df):,} of {total:,} rows")

    col_cfg = {
        "Manual Review Flag":           st.column_config.TextColumn(width="small"),
        "High Value HCC Flag":          st.column_config.TextColumn(width="small"),
        "Confidence Level":             st.column_config.TextColumn(width="small"),
        "Possible ICD-10-CM Code 1":    st.column_config.TextColumn(width="small"),
        "ICD-10 Description 1":         st.column_config.TextColumn(width="large"),
        "Possible ICD-10-CM Code 2":    st.column_config.TextColumn(width="small"),
        "ICD-10 Description 2":         st.column_config.TextColumn(width="large"),
        "Possible ICD-10-CM Code 3":    st.column_config.TextColumn(width="small"),
        "ICD-10 Description 3":         st.column_config.TextColumn(width="large"),
        "Possible ICD-10-CM Code 4":    st.column_config.TextColumn(width="small"),
        "ICD-10 Description 4":         st.column_config.TextColumn(width="large"),
        "HCC Category (ICD 1)":         st.column_config.TextColumn(width="small"),
        "HCC Category (ICD 2)":         st.column_config.TextColumn(width="small"),
        "HCC Category (ICD 3)":         st.column_config.TextColumn(width="small"),
        "HCC Category (ICD 4)":         st.column_config.TextColumn(width="small"),
        "Data Source":                  st.column_config.TextColumn(width="medium"),
    }
    if mode == "freetext":
        col_cfg["Row Number"] = st.column_config.NumberColumn(width="small")

    st.dataframe(display_df, use_container_width=True, height=540, hide_index=True, column_config=col_cfg)

    # ── High-value HCC callout ────────────────────────────────────────────────
    if "High Value HCC Flag" in df.columns:
        hcc_df = df[df["High Value HCC Flag"].str.startswith("YES", na=False)]
        if not hcc_df.empty:
            hcc_show = [c for c in [
                "MedicationsID", "DocID", "DateOfService",
                "Row Number", "Original Input",
                "Normalized Generic Name",
                "Possible ICD-10-CM Code 1", "HCC Category (ICD 1)", "HCC Description (ICD 1)",
                "Possible ICD-10-CM Code 2", "HCC Category (ICD 2)", "HCC Description (ICD 2)",
                "Possible ICD-10-CM Code 3", "HCC Category (ICD 3)", "HCC Description (ICD 3)",
                "Possible ICD-10-CM Code 4", "HCC Category (ICD 4)", "HCC Description (ICD 4)",
            ] if c in hcc_df.columns]
            with st.expander(f"🏷 High Value HCC Detected — {len(hcc_df):,} medication(s)", expanded=True):
                st.caption("These medications have potential ICD codes that map to high-value HCC categories in CMS-HCC Model v28. Manual clinical review recommended.")
                st.dataframe(hcc_df[hcc_show], use_container_width=True, hide_index=True)

    # ── Manual review callout ─────────────────────────────────────────────────
    review_df = df[df["Manual Review Flag"] == "YES"]
    if not review_df.empty:
        review_show = [c for c in [
            "MedicationsID", "DocID", "DateOfService",
            "Row Number", "Original Input",
            "Normalized Generic Name", "Confidence Level",
            "High Value HCC Flag", "Data Source", "Ambiguity Notes",
        ] if c in review_df.columns]
        with st.expander(f"⚠️ Manual Review Required — {len(review_df):,} row(s)", expanded=False):
            st.dataframe(review_df[review_show], use_container_width=True, hide_index=True)

    # ── Exports ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">Step 3 — Export Results</div>', unsafe_allow_html=True)
    st.caption("Exports use the full unfiltered results table.")

    ex1, ex2 = st.columns(2)

    with ex1:
        try:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Results", index=False)
                ws = writer.sheets["Results"]
                ws.freeze_panes = "A2"
                for col_cells in ws.columns:
                    max_len = max(
                        (len(str(c.value)) if c.value is not None else 0)
                        for c in col_cells
                    )
                    ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 55)
            buf.seek(0)
            st.download_button(
                "📥 Download Excel (.xlsx)", data=buf,
                file_name="medication_indication_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Excel export error: {e}")

    with ex2:
        try:
            txt_buf = io.StringIO()
            df.to_csv(txt_buf, sep="\t", index=False)
            st.download_button(
                "📥 Download Text (.txt, tab-delimited)", data=txt_buf.getvalue().encode("utf-8"),
                file_name="medication_indication_results.txt",
                mime="text/plain",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Text export error: {e}")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Medication Indication Mapper · Research/Support Tool · Not for clinical diagnosis or billing · "
    "ICD-10 from local dictionary · ICD-10 descriptions: NLM API · HCC: CMS-HCC v28 crosswalk (research use only) · "
    "RxNorm: NLM API · NDC: openFDA API"
)
