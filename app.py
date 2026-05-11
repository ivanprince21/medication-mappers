"""
Medication Indication Mapper — HealthSmartMSO
=============================================
Web app (Streamlit). Two input modes:
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
from datetime import datetime, timezone, timedelta

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
from version       import VERSION, RELEASE_DATE, CHANGELOG
from react_dashboard  import render_react_dashboard

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="HealthSmartMSO — ICD Extraction",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ── Global reset — white bg, dark readable text ── */
html, body {
    font-family: 'Inter', 'Segoe UI', sans-serif !important;
    background-color: #ffffff !important;
    color: #212121 !important;
}
[class*="css"] {
    font-family: 'Inter', 'Segoe UI', sans-serif !important;
}

/* Streamlit containers */
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="block-container"],
section[data-testid="stSidebar"],
.main, .stApp {
    background-color: #ffffff !important;
    color: #212121 !important;
}

/* ── Full-width 2048px layout — zero side whitespace ── */
.block-container,
[data-testid="block-container"] {
    padding-top: 0 !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    max-width: 2048px !important;
    width: 100% !important;
    background: #ffffff;
}
[data-testid="stMain"] > div:first-child {
    padding-left: 0 !important;
    padding-right: 0 !important;
    max-width: 100% !important;
}
section.main > div {
    max-width: 2048px !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}

/* All plain text, markdown, paragraphs */
p, span, li, td, th, div,
[data-testid="stMarkdown"],
[data-testid="stMarkdown"] p,
[data-testid="stMarkdown"] li,
[data-testid="stText"],
[data-testid="stCaption"] {
    color: #212121 !important;
}

/* Labels on all widgets */
label, .stSelectbox label, .stTextInput label,
.stMultiSelect label, .stSlider label,
.stRadio label, .stCheckbox label,
.stDateInput label, .stNumberInput label,
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p {
    color: #003153 !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
}

/* Selectbox / dropdown text */
div[data-baseweb="select"] [data-testid="stMarkdown"],
div[data-baseweb="select"] span,
div[data-baseweb="select"] div {
    color: #212121 !important;
}

/* Input field text */
input, textarea {
    color: #212121 !important;
    background-color: #ffffff !important;
}

/* Captions */
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p {
    color: #556677 !important;
    font-size: 0.80rem !important;
}

/* Success / info / warning / error boxes */
[data-testid="stAlert"] { color: inherit !important; }

/* Expander content area */
[data-testid="stExpander"] details summary p,
[data-testid="stExpander"] details div p {
    color: #212121 !important;
}

/* st.info / st.success / st.warning text */
.stAlert p { color: inherit !important; }

/* ── Header — force all text white ── */
.app-header,
.app-header p,
.app-header span,
.app-header div,
.app-header li,
.header-body,
.header-body p,
.header-body span,
.header-body div,
.header-top-bar,
.header-top-bar p,
.header-top-bar span,
.header-top-bar div { color: #ffffff !important; }

.app-header .header-top-bar,
.app-header .header-top-bar * { color: rgba(255,255,255,0.65) !important; }
.app-header .brand-org         { color: #29b6f6 !important; }
.app-header .app-title         { color: #ffffff !important; }
.app-header .app-tagline       { color: rgba(255,255,255,0.55) !important; }
.app-header .header-meta-line  { color: rgba(255,255,255,0.6) !important; }
.app-header .header-meta-label { color: rgba(255,255,255,0.38) !important; }
.app-header .version-pill      { color: #003153 !important; }
.app-header .header-meta-line  { color: #003153 !important; }
.app-header .header-meta-label { color: rgba(0,49,83,0.65) !important; }

/* ── Header banner — HealthSmart MSO blue ── */
.app-header {
    background: linear-gradient(135deg, #003153 0%, #0a4a7a 45%, #1863dc 80%, #29b6f6 100%);
    padding: 0;
    border-radius: 0;
    margin-bottom: 1.4rem;
    box-shadow: 0 8px 32px rgba(24,99,220,0.28), 0 2px 8px rgba(0,0,0,0.15);
    overflow: hidden;
}
.header-top-bar {
    background: rgba(0,0,0,0.15);
    padding: 5px 2rem;
    font-size: 0.69rem;
    color: rgba(255,255,255,0.65);
    letter-spacing: 0.3px;
    display: flex;
    justify-content: space-between;
}
.header-body {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.3rem 2rem 1.5rem 2rem;
}
.header-left { display: flex; align-items: center; gap: 1.4rem; flex: 1; }
.header-logo img {
    height: 68px;
    border-radius: 10px;
    background: white;
    padding: 5px 10px;
    box-shadow: 6px 6px 9px rgba(0,0,0,0.28);
}
.header-text { flex: 1; }
.brand-org {
    font-size: 0.67rem;
    font-weight: 700;
    color: #29b6f6;
    letter-spacing: 2.8px;
    text-transform: uppercase;
    margin-bottom: 4px;
}
.app-title {
    font-size: 1.6rem;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.4px;
    line-height: 1.2;
    margin-bottom: 6px;
}
.app-tagline {
    font-size: 0.74rem;
    color: rgba(255,255,255,0.55);
    font-style: italic;
    font-weight: 400;
}
.header-right { text-align: right; flex-shrink: 0; }
.version-pill {
    display: inline-block;
    background: rgba(0,0,0,0.12);
    border: 1px solid rgba(0,49,83,0.35);
    color: #29b6f6;
    padding: 3px 14px;
    border-radius: 9999px;
    font-size: 0.74rem;
    font-weight: 600;
    margin-bottom: 7px;
    letter-spacing: 0.3px;
}
.header-meta-line {
    color: rgba(255,255,255,0.6);
    font-size: 0.74rem;
    line-height: 1.9;
}
.header-meta-label {
    color: rgba(255,255,255,0.38);
    font-size: 0.68rem;
}

/* ── Disclaimer ── */
.disclaimer-box {
    background: linear-gradient(135deg, #fefce8 0%, #fffbeb 100%);
    border-left: 4px solid #f0a500;
    padding: 0.55rem 1.2rem;
    border-radius: 10px;
    font-size: 0.82rem;
    color: #5d4037;
    margin-bottom: 1rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05), 2px 0 8px rgba(240,165,0,0.08);
}

/* ── About section ── */
.about-box {
    background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%);
    border: 1px solid #e2eef8;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1rem;
    font-size: 0.87rem;
    color: #212121;
    line-height: 1.7;
    box-shadow: 0 4px 20px rgba(24,99,220,0.08);
}
.about-box h4 {
    color: #003153;
    font-size: 1rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
}
.about-step {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin-bottom: 6px;
}
.step-num {
    background: linear-gradient(135deg, #003153, #1863dc);
    color: white;
    border-radius: 50%;
    width: 23px;
    height: 23px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.72rem;
    font-weight: 700;
    flex-shrink: 0;
    margin-top: 2px;
    box-shadow: 0 2px 6px rgba(24,99,220,0.35);
}

/* ── API status badges ── */
.api-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 14px;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-right: 5px;
    margin-bottom: 4px;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.api-badge:hover { transform: translateY(-1px); }
.api-online  { background: linear-gradient(135deg, #e8f5e9, #f1fdf2); color: #1b5e20; border: 1px solid #a5d6a7; }
.api-offline { background: linear-gradient(135deg, #ffebee, #fff5f5); color: #b71c1c; border: 1px solid #ef9a9a; }
.api-local   { background: linear-gradient(135deg, #e3f2fd, #eef8ff); color: #003153; border: 1px solid #90caf9; }

/* ── Section headers ── */
.section-header {
    font-size: 0.94rem;
    font-weight: 700;
    color: #003153;
    border-left: 3px solid #1863dc;
    padding-left: 10px;
    margin: 1rem 0 0.8rem 0;
    letter-spacing: 0.2px;
    text-shadow: 0 1px 2px rgba(24,99,220,0.08);
}

/* ── Required columns display ── */
.req-cols {
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 0.78rem;
    background: linear-gradient(135deg, #eaf4fb, #f0f8ff);
    border: 1px solid #b8ddf5;
    padding: 0.5rem 1rem;
    border-radius: 8px;
    color: #003153;
    box-shadow: 0 2px 8px rgba(24,99,220,0.06);
}

/* ── Metric cards ── */
.metric-card {
    background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%);
    border: 1px solid #e2eef8;
    border-top: 4px solid #29b6f6;
    border-radius: 12px;
    padding: 1rem 1.2rem;
    text-align: center;
    box-shadow: 0 4px 24px rgba(24,99,220,0.10), 0 1px 4px rgba(0,0,0,0.04);
    transition: transform 0.2s ease, box-shadow 0.25s ease;
}
.metric-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 32px rgba(24,99,220,0.20), 0 2px 8px rgba(0,0,0,0.06);
}
.metric-value {
    font-size: 2.2rem;
    font-weight: 900;
    color: #003153;
    line-height: 1.1;
}
.metric-label {
    font-size: 0.70rem;
    color: #1863dc;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-top: 3px;
}

/* ── Run report banner ── */
.run-report-banner {
    background: linear-gradient(135deg, #003153 0%, #0a4a7a 50%, #1863dc 100%);
    color: white;
    padding: 0.85rem 1.5rem;
    border-radius: 12px;
    font-size: 0.82rem;
    margin-bottom: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-left: 4px solid #29b6f6;
    box-shadow: 0 4px 24px rgba(24,99,220,0.30), 0 1px 6px rgba(0,0,0,0.10);
}
.run-report-title { font-weight: 700; font-size: 0.93rem; color: #ffffff; }
.run-report-meta  { color: rgba(255,255,255,0.6); font-size: 0.78rem; }

/* ── HCC flag ── */
.hcc-flag {
    color: #856404;
    background: #fff3cd;
    border: 1px solid #f0a500;
    padding: 4px 14px;
    border-radius: 9999px;
    font-size: 0.78rem;
    font-weight: 600;
}

/* ── Dataframe ── */
div[data-testid="stDataFrame"] { font-size: 0.81rem; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: #f0f7ff;
    border-radius: 9999px;
    padding: 4px 8px;
    gap: 4px;
    border: 1px solid #d0e8f5;
    box-shadow: 0 2px 8px rgba(24,99,220,0.06);
}
.stTabs [data-baseweb="tab"] {
    font-weight: 600;
    font-size: 0.85rem;
    color: #4a6080;
    border-radius: 9999px;
    padding: 7px 18px;
    transition: all 0.2s ease;
    letter-spacing: 0.1px;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #003153, #1863dc) !important;
    color: #ffffff !important;
    box-shadow: 0 4px 16px rgba(24,99,220,0.35);
    letter-spacing: 0.2px;
}

/* ── Buttons ── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #003153, #1863dc);
    border: none;
    border-radius: 9999px;
    font-weight: 600;
    letter-spacing: 0.3px;
    box-shadow: 0 4px 16px rgba(24,99,220,0.35), 0 1px 4px rgba(0,0,0,0.1);
    transition: all 0.2s ease;
    padding: 0.5rem 1.8rem;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #1863dc, #29b6f6);
    box-shadow: 0 6px 24px rgba(41,182,246,0.45), 0 2px 8px rgba(0,0,0,0.1);
    transform: translateY(-2px);
}

/* ── Download buttons ── */
.stDownloadButton > button {
    border-radius: 9999px;
    font-weight: 600;
    font-size: 0.84rem;
    border: 1.5px solid #1863dc !important;
    color: #1863dc !important;
    background: linear-gradient(135deg, #ffffff, #f5f9ff) !important;
    transition: all 0.2s ease;
    box-shadow: 0 2px 12px rgba(24,99,220,0.10);
}
.stDownloadButton > button:hover {
    background: linear-gradient(135deg, #003153, #1863dc) !important;
    color: #ffffff !important;
    box-shadow: 0 4px 20px rgba(24,99,220,0.35);
    transform: translateY(-2px);
}

/* ── Expander ── */
.streamlit-expanderHeader {
    font-weight: 600 !important;
    color: #003153 !important;
    background: linear-gradient(135deg, #f0f6ff, #eaf4fb) !important;
    border-radius: 10px !important;
    box-shadow: 0 2px 8px rgba(24,99,220,0.06) !important;
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span {
    color: #003153 !important;
    font-weight: 600 !important;
}

/* ── Tabs bar background + text ── */
.stTabs [data-baseweb="tab-list"] {
    background: #f0f7ff !important;
}
.stTabs [data-baseweb="tab"] p,
.stTabs [data-baseweb="tab"] span,
.stTabs [data-baseweb="tab"] div {
    color: #003153 !important;
}
.stTabs [aria-selected="true"] p,
.stTabs [aria-selected="true"] span,
.stTabs [aria-selected="true"] div {
    color: #ffffff !important;
}

/* ── Selectbox / inputs ── */
div[data-baseweb="select"] > div {
    border-radius: 10px !important;
    border-color: #d0dff0 !important;
    background-color: #ffffff !important;
    color: #212121 !important;
    box-shadow: 0 1px 4px rgba(24,99,220,0.06) !important;
}
div[data-baseweb="select"] span { color: #212121 !important; }
div[data-baseweb="input"] > div {
    border-radius: 10px !important;
    border-color: #d0dff0 !important;
    background-color: #ffffff !important;
    box-shadow: 0 1px 4px rgba(24,99,220,0.06) !important;
}
div[data-baseweb="input"] input { color: #212121 !important; }

/* ── File uploader ── */
[data-testid="stFileUploader"] label,
[data-testid="stFileUploader"] p,
[data-testid="stFileUploader"] span {
    color: #003153 !important;
}

/* ── Horizontal rule ── */
hr { border-color: #e8eef6 !important; }

/* ── Dataframe cell text ── */
div[data-testid="stDataFrame"] { font-size: 0.82rem; color: #212121; }

/* ── Drill-down filter banner ── */
[data-testid="stMarkdown"] div[style*="background:#eaf4fb"] {
    background: #f0f7ff !important;
}

/* ── HCC flag pill ── */
.hcc-flag {
    color: #856404;
    background: linear-gradient(135deg, #fff3cd, #fef9e7);
    border: 1px solid #f0a500;
    padding: 4px 14px;
    border-radius: 9999px;
    font-size: 0.78rem;
    font-weight: 600;
    box-shadow: 0 2px 8px rgba(240,165,0,0.15);
}
</style>
""", unsafe_allow_html=True)

# ── Now datetime ──────────────────────────────────────────────────────────────
_PST = timezone(timedelta(hours=-8))
_NOW = datetime.now(tz=_PST)
_NOW_STR = _NOW.strftime("%B %d, %Y  %I:%M %p PST")

# ── Header banner ─────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="app-header">
  <div class="header-top-bar">
    <span>HealthSmart Management Services Organization, Inc. &nbsp;·&nbsp; Cypress, CA 90630 &nbsp;·&nbsp; (714) 947-8600 &nbsp;·&nbsp; info@healthsmartmso.com</span>
    <span>Advance with Integrity &nbsp;·&nbsp; Value the Community &nbsp;·&nbsp; Welcome Opportunities &nbsp;·&nbsp; Strive for Excellence</span>
  </div>
  <div class="header-body">
    <div class="header-left">
      <div class="header-logo">
        <img src="https://healthsmartmso.com/wp-content/uploads/2025/10/logo_hsmso.jpg"
             alt="HealthSmart MSO Logo"
             onerror="this.style.display='none'">
      </div>
      <div class="header-text">
        <div class="brand-org">HealthSmart Management Services Organization, Inc.</div>
        <div class="app-title">ICD Extraction from Medication</div>
        <div class="app-tagline">
          Medication-to-ICD-10-CM mapping &nbsp;·&nbsp;
          CMS-HCC v28 risk enrichment &nbsp;·&nbsp;
          Clinical Support &amp; Research Tool
        </div>
      </div>
    </div>
    <div class="header-right">
      <div class="version-pill">v{VERSION} &nbsp;·&nbsp; {RELEASE_DATE}</div><br>
      <div class="header-meta-line">
        <span class="header-meta-label">Session started</span><br>
        {_NOW_STR}
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Disclaimer ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="disclaimer-box">
  ⚠️ <strong>Disclaimer:</strong>
  This tool provides <strong>possible</strong> medication indications,
  <strong>possible</strong> ICD-10-CM codes, and <strong>possible</strong> HCC categories
  for <strong>research and support review use only</strong>.
  It does <strong>not</strong> diagnose, confirm a condition, confirm an HCC assignment,
  or replace clinical judgment.
  All outputs are possible indications only — not confirmed diagnoses or final billing codes.
</div>
""", unsafe_allow_html=True)

# ── API status ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def get_api_status():
    icd10_ok = bool(_icd10_ping("E11.9"))
    return check_api_available(), check_ndc_api_available(), icd10_ok

rxnorm_ok, ndc_ok, icd10_ok = get_api_status()

def _badge(label, ok, local=False):
    if local:
        return f'<span class="api-badge api-local">🔵 {label}</span>'
    cls = "api-online" if ok else "api-offline"
    dot = "🟢" if ok else "🔴"
    txt = "Online" if ok else "Offline"
    return f'<span class="api-badge {cls}">{dot} {label}: {txt}</span>'

st.markdown(
    _badge("RxNorm API", rxnorm_ok) +
    _badge("openFDA NDC API", ndc_ok) +
    _badge("ICD-10 NLM API", icd10_ok) +
    _badge("HCC v28 Crosswalk — Offline Capable", True, local=True),
    unsafe_allow_html=True,
)
st.markdown("<div style='margin-bottom:0.8rem'></div>", unsafe_allow_html=True)

# ── About / Instructions ──────────────────────────────────────────────────────
with st.expander("📋  About This Project — Purpose, Instructions & Data Flow", expanded=False):
    st.markdown("""
<div class="about-box">

<h4>🎯 Purpose</h4>
<p>
The <strong>HealthSmartMSO ICD Extraction from Medication</strong> project automates the process of mapping
member medication lists to <strong>possible ICD-10-CM diagnosis codes</strong> and
<strong>CMS-HCC Model v28 risk categories</strong>.
It is designed to support clinical reviewers and coding teams in identifying potential diagnoses
that may need to be validated or documented — reducing manual lookup time and surfacing
high-value HCC opportunities for review.
</p>

<h4>👥 Who It's For</h4>
<ul>
  <li><strong>Clinical support staff</strong> reviewing member medication profiles</li>
  <li><strong>HCC coding teams</strong> identifying potential risk-adjustment opportunities</li>
  <li><strong>Care management teams</strong> validating medication-diagnosis alignment</li>
</ul>

<h4>📌 How to Use</h4>
<div class="about-step"><span class="step-num">1</span><span>
  <strong>Prepare your file.</strong> Export a structured medication list from your EHR or pharmacy system.
  The file must be CSV or Excel format with the 8 required columns listed in the upload tab.
  Each row represents one medication for one member.
</span></div>
<div class="about-step"><span class="step-num">2</span><span>
  <strong>Upload and validate.</strong> Use the <em>Structured File Upload</em> tab to upload your file.
  The tool validates required columns and previews your data before processing.
</span></div>
<div class="about-step"><span class="step-num">3</span><span>
  <strong>Process.</strong> Click <em>Parse / Process</em>. The tool routes each medication through
  the appropriate lookup engine (RxNorm API, openFDA NDC API, or local dictionary),
  resolves ICD-10-CM codes, looks up descriptions from the NLM API, and enriches with HCC categories.
</span></div>
<div class="about-step"><span class="step-num">4</span><span>
  <strong>Review results.</strong> Use the filter controls to focus on Manual Review rows,
  High Value HCC flags, or specific drugs. The High Value HCC callout section highlights
  medications with potential HCC-mapped diagnoses.
</span></div>
<div class="about-step"><span class="step-num">5</span><span>
  <strong>Export.</strong> Download the full results as Excel (.xlsx) for further review,
  annotation, or submission to the clinical team.
</span></div>

<h4>🔄 Lookup & Data Flow</h4>
<table style="width:100%; font-size:0.83rem; border-collapse:collapse;">
  <tr style="background:#e8f0fb; font-weight:600;">
    <td style="padding:6px 10px; border:1px solid #c8d8ed">Code System</td>
    <td style="padding:6px 10px; border:1px solid #c8d8ed">Lookup Engine</td>
    <td style="padding:6px 10px; border:1px solid #c8d8ed">What It Returns</td>
  </tr>
  <tr>
    <td style="padding:6px 10px; border:1px solid #dde8f5">RxNorm / RXN</td>
    <td style="padding:6px 10px; border:1px solid #dde8f5">NLM RxNorm API + Local Dictionary</td>
    <td style="padding:6px 10px; border:1px solid #dde8f5">Generic name, drug class, indications, ICD-10 codes, HCC</td>
  </tr>
  <tr style="background:#f8faff;">
    <td style="padding:6px 10px; border:1px solid #dde8f5">NDC</td>
    <td style="padding:6px 10px; border:1px solid #dde8f5">openFDA NDC API + Local Dictionary</td>
    <td style="padding:6px 10px; border:1px solid #dde8f5">Generic name, brand, dosage form, ICD-10 codes, HCC</td>
  </tr>
  <tr>
    <td style="padding:6px 10px; border:1px solid #dde8f5">Other / Display Name</td>
    <td style="padding:6px 10px; border:1px solid #dde8f5">Local Dictionary (text match)</td>
    <td style="padding:6px 10px; border:1px solid #dde8f5">Full mapping if drug is in dictionary; manual review flag if not</td>
  </tr>
  <tr style="background:#f8faff;">
    <td style="padding:6px 10px; border:1px solid #dde8f5">Not found anywhere</td>
    <td style="padding:6px 10px; border:1px solid #dde8f5">NLM ICD-10-CM live search (by drug class)</td>
    <td style="padding:6px 10px; border:1px solid #dde8f5">Possible ICD codes from live search — low confidence, manual review required</td>
  </tr>
</table>

<h4 style="margin-top:1rem">⚠️ Important Limitations</h4>
<ul>
  <li>All ICD-10-CM codes returned are <strong>possible</strong> — they must be validated by a qualified clinician or coder.</li>
  <li>HCC assignments are based on the local CMS-HCC Model v28 crosswalk for <strong>research purposes only</strong>.</li>
  <li>This tool does <strong>not</strong> access member clinical records — it maps medications to possible diagnoses based on known pharmacological indications.</li>
  <li>Drugs not in the local dictionary receive a <strong>Low confidence / Manual Review</strong> flag automatically.</li>
</ul>

</div>
""", unsafe_allow_html=True)

# ── Changelog ─────────────────────────────────────────────────────────────────
with st.expander(f"📝  Version History — Current: v{VERSION}", expanded=False):
    st.markdown(CHANGELOG)

st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# INPUT TABS
# ═════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="section-header">Input Medication Data</div>', unsafe_allow_html=True)

tab_struct, tab_text = st.tabs([
    "📋  Structured File Upload (CSV / Excel)  ← Primary",
    "✏️   Free Text / Paste  ← Quick Test",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Structured File
# ─────────────────────────────────────────────────────────────────────────────
with tab_struct:

    st.markdown("**Required columns** (exact names, case-insensitive):")
    st.markdown(
        '<div class="req-cols">' + " &nbsp;|&nbsp; ".join(REQUIRED_INPUT_COLS) + "</div>",
        unsafe_allow_html=True,
    )

    with st.expander("📌 How lookup routing works"):
        st.markdown("""
| `MedicationsCodeSystemName` value | Lookup used |
|---|---|
| `RxNorm`, `rxnorm`, `RXN`, `rxnorm code` | **NLM RxNorm API** — `MedicationsCode` treated as RXCUI |
| `NDC`, `ndc`, `National Drug Code`, `ndc11`, `ndc10` | **openFDA NDC API** — `MedicationsCode` treated as NDC |
| Anything else | **Local dictionary** — text match on `MedicationsCodeDisplayName` |

After ICD codes are resolved from the local dictionary, each code is:
1. Looked up in the **NLM ICD-10-CM API** (or local cache) for a full description
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

            st.success(f"✔  **{struct_file.name}** — {len(df_input):,} rows, {len(df_input.columns)} columns")

            input_cols_lower = {c.lower().strip() for c in df_input.columns}
            missing_cols     = [c for c in REQUIRED_INPUT_COLS if c.lower().strip() not in input_cols_lower]
            extra_cols       = [c for c in df_input.columns if c.lower().strip() not in {r.lower() for r in REQUIRED_INPUT_COLS}]

            if missing_cols:
                st.error(f"Missing required columns: **{missing_cols}**")
                st.stop()
            else:
                st.success("✔  All required columns found.")
            if extra_cols:
                st.info(f"Extra columns (will be ignored): {extra_cols}")

            with st.expander("Preview first 10 rows"):
                st.dataframe(df_input.head(10), use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Could not read file: {e}")
            df_input = None

    st.markdown('<div class="section-header">Process</div>', unsafe_allow_html=True)
    run_struct = st.button(
        "🔍  Parse / Process Structured File",
        type="primary",
        key="run_struct",
        disabled=(df_input is None),
    )

    if run_struct and df_input is not None:
        try:
            with st.spinner(f"Processing {len(df_input):,} rows — deduplicating codes and querying APIs in parallel…"):
                result_df = parse_structured_dataframe(df_input)
            st.session_state["results_df"]      = result_df
            st.session_state["results_mode"]    = "structured"
            st.session_state["run_datetime"]    = datetime.utcnow()
            st.session_state["run_file_name"]   = struct_file.name if struct_file else ""
            st.session_state["run_row_count"]   = len(result_df)
            st.session_state.pop("drill_filter", None)
            st.success(f"✔  Done — {len(result_df):,} rows processed.")
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
    with st.expander("ℹ️  Supported free-text formats"):
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
            st.success(f"✔  Loaded: {ft_file.name} ({len(raw_text.splitlines())} lines)")
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
            placeholder="Metformin 500 mg\nRXCUI:860975\n…",
        )
    if pasted.strip():
        raw_text = pasted

    st.markdown('<div class="section-header">Process</div>', unsafe_allow_html=True)
    run_free = st.button("🔍  Parse / Process Free Text", type="primary", key="run_free")

    if run_free:
        if not raw_text or not raw_text.strip():
            st.error("No input provided.")
        else:
            with st.spinner("Parsing…"):
                try:
                    results = parse_medication_list(raw_text)
                    if not results:
                        st.warning("No medication lines found.")
                    else:
                        st.session_state["results_df"]    = pd.DataFrame(results)
                        st.session_state["results_mode"]  = "freetext"
                        st.session_state["run_datetime"]  = datetime.utcnow()
                        st.session_state["run_file_name"] = "Free-text input"
                        st.session_state["run_row_count"] = len(results)
                except Exception as e:
                    st.error(f"Parsing error: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# RESULTS
# ═════════════════════════════════════════════════════════════════════════════
if "results_df" in st.session_state:
    df: pd.DataFrame = st.session_state["results_df"]
    mode: str        = st.session_state.get("results_mode", "freetext")
    run_dt           = st.session_state.get("run_datetime")
    run_file         = st.session_state.get("run_file_name", "")
    run_rows         = st.session_state.get("run_row_count", len(df))

    st.markdown("---")

    # ── Run report banner ─────────────────────────────────────────────────────
    run_dt_str = run_dt.strftime("%B %d, %Y  %I:%M:%S %p UTC") if run_dt else "—"
    st.markdown(f"""
<div class="run-report-banner">
  <div>
    <div class="run-report-title">📊 Report Results</div>
    <div class="run-report-meta">
      Source: <strong>{run_file}</strong> &nbsp;·&nbsp;
      {run_rows:,} rows processed
    </div>
  </div>
  <div style="text-align:right">
    <div class="run-report-meta">Report generated</div>
    <div style="color:#ffffff; font-weight:600; font-size:0.85rem">{run_dt_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Summary metrics ───────────────────────────────────────────────────────
    total        = len(df)
    unknown_mask = df["Normalized Generic Name"].isin(["Unknown Medication", "Unknown"])
    recognized   = int((~unknown_mask).sum())
    unknown      = int(unknown_mask.sum())
    need_review  = int((df["Manual Review Flag"] == "YES").sum())
    high_hcc     = int(df["High Value HCC Flag"].str.startswith("YES").sum()) if "High Value HCC Flag" in df.columns else 0
    api_rows     = int(df["Data Source"].str.contains("API", na=False).sum()) if "Data Source" in df.columns else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    for col, val, label in [
        (c1, total,      "Total Rows"),
        (c2, recognized, "Recognized"),
        (c3, unknown,    "Unknown"),
        (c4, need_review,"Manual Review"),
        (c5, high_hcc,   "High Value HCC"),
        (c6, api_rows,   "Via External API"),
    ]:
        col.markdown(f"""
<div class="metric-card">
  <div class="metric-value">{val:,}</div>
  <div class="metric-label">{label}</div>
</div>""", unsafe_allow_html=True)

    st.markdown("<div style='margin-bottom:0.5rem'></div>", unsafe_allow_html=True)

    # ── React Analytics Dashboard (from processed results) ───────────────────
    render_react_dashboard(df)

    # ── Filters ───────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Filter Results</div>', unsafe_allow_html=True)
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)

    with fc1:
        search = st.text_input("Search:", placeholder="drug, ICD, HCC, condition…")
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

    # ── Drill-down filter (from chart click) ──────────────────────────────────
    drill = st.session_state.get("drill_filter")
    if drill:
        import re as _re
        drill_val  = drill["value"]
        drill_cols = [c for c in drill["columns"] if c in display_df.columns]
        drill_label = drill.get("label", drill_val)

        if drill_cols:
            # Build OR mask across all target columns
            mask = pd.Series(False, index=display_df.index)
            for col in drill_cols:
                mask |= display_df[col].astype(str).str.contains(
                    _re.escape(drill_val), case=False, na=False
                )
            display_df = display_df[mask]

        # Active filter banner
        st.markdown(f"""
<div style="background:#eaf4fb; border:1px solid #1863dc; border-left:4px solid #1863dc;
     border-radius:8px; padding:0.55rem 1rem; margin-bottom:0.6rem;
     display:flex; justify-content:space-between; align-items:center;">
  <div style="color:#003153; font-size:0.84rem;">
    🔍 <strong>Drill-down active:</strong> &nbsp;<em>{drill_label}</em>
    &nbsp;·&nbsp; <span style="color:#556677;">Click the same bar/slice again to clear,
    or use the button →</span>
  </div>
</div>""", unsafe_allow_html=True)
        if st.button("✕  Clear drill-down filter", key="clear_drill"):
            st.session_state.pop("drill_filter", None)
            st.rerun()

    st.caption(f"Showing **{len(display_df):,}** of **{total:,}** rows"
               + (f" · drill-down: **{drill['label']}**" if drill else ""))

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
            with st.expander(f"🏷  High Value HCC Detected — {len(hcc_df):,} medication(s)", expanded=True):
                st.caption("These medications have potential ICD codes mapping to high-value HCC categories in CMS-HCC Model v28. Manual clinical review recommended.")
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
        with st.expander(f"⚠️  Manual Review Required — {len(review_df):,} row(s)", expanded=False):
            st.dataframe(review_df[review_show], use_container_width=True, hide_index=True)

    # ── Exports ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-header">Export Results</div>', unsafe_allow_html=True)
    st.caption(
        "Exports use a **condensed format** — all ICD codes, indications, and HCC fields combined "
        "into single columns for readability. Full unfiltered results."
    )

    def _condense_for_export(raw: pd.DataFrame) -> pd.DataFrame:
        """Flatten multi-slot ICD / indication / HCC columns into single pipe-joined columns."""
        def _get(col):
            return raw.get(col, pd.Series([""] * len(raw), index=raw.index)).fillna("").astype(str)

        _SKIP = {"", "nan", "n/a", "n/a — not in local dictionary", "none"}

        def _join(*cols):
            parts = pd.concat([_get(c).rename(c) for c in cols], axis=1)
            return parts.apply(
                lambda r: " | ".join(v.strip() for v in r if v.strip().lower() not in _SKIP),
                axis=1,
            )

        def _trunc(col, n):
            return _get(col).apply(lambda x: (x[:n] + "…") if len(x) > n else x)

        out = pd.DataFrame(index=raw.index)

        if "Row Number"    in raw.columns: out["Row Number"]    = _get("Row Number")
        if "Original Input" in raw.columns: out["Original Input"] = _get("Original Input")

        out["MedicationID"]               = _get("MedicationsID")
        out["DocID"]                      = _get("DocID")
        out["DateOfService"]              = _get("DateOfService")
        out["Generic Name"]               = _get("Normalized Generic Name")
        out["Brand Name Match"]           = _get("Brand Name Match")
        out["Dosage"]                     = _get("Dosage")
        out["Possible Indications"]       = _join(
            "Possible Indication 1", "Possible Indication 2", "Possible Indication 3"
        )
        out["Why Member Takes This Drug"] = _get("Why Member May Take This Drug")
        out["Possible ICD-10-CM Codes"]   = _join(
            "Possible ICD-10-CM Code 1", "Possible ICD-10-CM Code 2",
            "Possible ICD-10-CM Code 3", "Possible ICD-10-CM Code 4",
        )
        out["HCC Category"]               = _join(
            "HCC Category (ICD 1)", "HCC Category (ICD 2)",
            "HCC Category (ICD 3)", "HCC Category (ICD 4)",
        )
        out["HCC Model Hierarchy"]        = _join(
            "HCC Model Hierarchy (ICD 1)", "HCC Model Hierarchy (ICD 2)",
            "HCC Model Hierarchy (ICD 3)", "HCC Model Hierarchy (ICD 4)",
        )
        out["High Value HCC Flag"]        = _get("High Value HCC Flag")
        out["Confidence Level"]           = _get("Confidence Level")
        out["Manual Review Flag"]         = _get("Manual Review Flag")
        out["Ambiguity Notes"]            = _trunc("Ambiguity Notes", 150)
        out["Data Source"]                = _trunc("Data Source", 80)
        return out

    export_df = _condense_for_export(df)

    ex1, ex2 = st.columns(2)

    with ex1:
        try:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                export_df.to_excel(writer, sheet_name="Results", index=False)
                ws = writer.sheets["Results"]
                ws.freeze_panes = "A2"
                for col_cells in ws.columns:
                    max_len = max(
                        (len(str(c.value)) if c.value is not None else 0)
                        for c in col_cells
                    )
                    ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 60)
            buf.seek(0)
            st.download_button(
                "📥  Download Excel (.xlsx)", data=buf,
                file_name="medication_indication_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Excel export error: {e}")

    with ex2:
        try:
            txt_buf = io.StringIO()
            export_df.to_csv(txt_buf, sep="\t", index=False)
            st.download_button(
                "📥  Download Text (.txt, tab-delimited)", data=txt_buf.getvalue().encode("utf-8"),
                file_name="medication_indication_results.txt",
                mime="text/plain",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Text export error: {e}")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:center;
     font-size:0.74rem; color:#888; padding: 0.3rem 0 1rem 0; border-top: 1px solid #e0e8f0; margin-top: 0.5rem;">
  <div>
    <strong style="color:#003153">HealthSmart Management Services Organization, Inc.</strong>
    &nbsp;·&nbsp; ICD Extraction from Medication &nbsp;·&nbsp;
    v{VERSION} ({RELEASE_DATE}) &nbsp;·&nbsp;
    <em>Research / Support Tool — Not for clinical diagnosis or billing</em>
  </div>
  <div style="text-align:right; color:#aaa;">
    ICD-10: NLM API + 2026 local cache &nbsp;·&nbsp;
    HCC: CMS-HCC v28 (research) &nbsp;·&nbsp;
    RxNorm: NLM &nbsp;·&nbsp; NDC: openFDA
  </div>
</div>
""", unsafe_allow_html=True)
