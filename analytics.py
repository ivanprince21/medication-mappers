"""
analytics.py — Chart-generating functions for the Medication Mapper dashboard.
All functions accept the full results DataFrame and return a Plotly Figure (or None).
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Brand palette — HealthSmart MSO ──────────────────────────────────────────
BRAND_COLORS = [
    "#003153", "#1863dc", "#29b6f6", "#0a5490",
    "#4a9fd4", "#7dc0e8", "#f0a500", "#e05c2a",
]

_LAYOUT_COMMON = dict(
    template="none",
    paper_bgcolor="#ffffff",
    plot_bgcolor="#eaf4fb",
    margin=dict(l=10, r=10, t=44, b=10),
    font=dict(family="Inter, Segoe UI, sans-serif", color="#212121"),
)

_EXCLUDE_VALS = {"", "nan", "n/a", "n/a — not in local dictionary", "none", "not mapped"}


def _clean(series: pd.Series) -> pd.Series:
    """Drop empties, NaNs, and known placeholder strings."""
    return series.dropna().astype(str).pipe(
        lambda s: s[~s.str.strip().str.lower().isin(_EXCLUDE_VALS)]
    ).pipe(lambda s: s[s.str.strip() != ""])


def _bar_layout(fig: go.Figure, title: str, height: int = 360) -> go.Figure:
    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=13, color="#003153"), x=0),
        height=height,
        showlegend=False,
        xaxis=dict(showgrid=True, gridcolor="#d0e8f5", zeroline=False, tickfont=dict(size=11)),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=11)),
        bargap=0.28,
        **_LAYOUT_COMMON,
    )
    return fig


def _donut_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=13, color="#003153"), x=0),
        height=330,
        legend=dict(font=dict(size=11), orientation="v"),
        **_LAYOUT_COMMON,
    )
    return fig


# ── 1. Top Medications ────────────────────────────────────────────────────────
def chart_top_medications(df: pd.DataFrame, n: int = 15) -> go.Figure:
    col = "Normalized Generic Name"
    counts = (
        _clean(df.get(col, pd.Series(dtype=str)))
        .pipe(lambda s: s[~s.isin(["Unknown Medication", "Unknown"])])
        .value_counts()
        .head(n)
        .sort_values(ascending=True)
    )
    colors = [BRAND_COLORS[i % len(BRAND_COLORS)] for i in range(len(counts))]
    fig = go.Figure(go.Bar(
        x=counts.values,
        y=counts.index,
        orientation="h",
        marker_color=colors,
    ))
    return _bar_layout(fig, "Top Medications by Frequency")


# ── 2. Top ICD Codes ──────────────────────────────────────────────────────────
def chart_top_icd_codes(df: pd.DataFrame, n: int = 15) -> go.Figure:
    code_cols = [c for c in df.columns if c.startswith("Possible ICD-10-CM Code")]
    all_codes = pd.concat([_clean(df[c]) for c in code_cols if c in df.columns], ignore_index=True)
    counts = all_codes.value_counts().head(n).sort_values(ascending=True)
    colors = [BRAND_COLORS[i % len(BRAND_COLORS)] for i in range(len(counts))]
    fig = go.Figure(go.Bar(
        x=counts.values,
        y=counts.index,
        orientation="h",
        marker_color=colors,
    ))
    return _bar_layout(fig, "Most Common ICD-10 Codes")


# ── 3. HCC Distribution ───────────────────────────────────────────────────────
def chart_hcc_distribution(df: pd.DataFrame, n: int = 10) -> go.Figure:
    hcc_cols = [c for c in df.columns if c.startswith("HCC Category (ICD")]
    all_hcc = pd.concat([_clean(df[c]) for c in hcc_cols if c in df.columns], ignore_index=True)
    counts = all_hcc.value_counts().head(n).sort_values(ascending=True)
    colors = [BRAND_COLORS[i % len(BRAND_COLORS)] for i in range(len(counts))]
    fig = go.Figure(go.Bar(
        x=counts.values,
        y=counts.index,
        orientation="h",
        marker_color=colors,
    ))
    return _bar_layout(fig, "HCC Category Distribution")


# ── 4. Confidence Breakdown ───────────────────────────────────────────────────
def chart_confidence_breakdown(df: pd.DataFrame) -> go.Figure:
    col = "Confidence Level"
    counts = _clean(df.get(col, pd.Series(dtype=str))).value_counts()
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(),
        values=counts.values.tolist(),
        hole=0.45,
        marker=dict(colors=BRAND_COLORS[:len(counts)]),
    ))
    return _donut_layout(fig, "Confidence Level Breakdown")


# ── 5. Manual Review Status ───────────────────────────────────────────────────
def chart_manual_review(df: pd.DataFrame) -> go.Figure:
    col = "Manual Review Flag"
    counts = _clean(df.get(col, pd.Series(dtype=str))).value_counts()
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(),
        values=counts.values.tolist(),
        hole=0.45,
        marker=dict(colors=BRAND_COLORS[:len(counts)]),
    ))
    return _donut_layout(fig, "Manual Review Status")


# ── 6. High Value HCC Flags ───────────────────────────────────────────────────
def chart_hcc_flag(df: pd.DataFrame) -> go.Figure:
    col = "High Value HCC Flag"
    series = _clean(df.get(col, pd.Series(dtype=str)))
    # Normalize: group all "YES — ..." variants into "High Value HCC"
    series = series.apply(
        lambda v: "High Value HCC" if str(v).upper().startswith("YES") else v
    )
    counts = series.value_counts()
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(),
        values=counts.values.tolist(),
        hole=0.45,
        marker=dict(colors=BRAND_COLORS[:len(counts)]),
    ))
    return _donut_layout(fig, "High Value HCC Flags")


# ── 7. Data Source Breakdown ──────────────────────────────────────────────────
def chart_data_source(df: pd.DataFrame, n: int = 8) -> go.Figure:
    col = "Data Source"
    counts = (
        _clean(df.get(col, pd.Series(dtype=str)))
        .value_counts()
        .head(n)
        .sort_values(ascending=True)
    )
    colors = [BRAND_COLORS[i % len(BRAND_COLORS)] for i in range(len(counts))]
    fig = go.Figure(go.Bar(
        x=counts.values,
        y=counts.index,
        orientation="h",
        marker_color=colors,
    ))
    return _bar_layout(fig, "Data Source Breakdown")


# ── 8. Date Trend ─────────────────────────────────────────────────────────────
def chart_date_trend(df: pd.DataFrame) -> go.Figure | None:
    col = "DateOfService"
    if col not in df.columns:
        return None
    dates = pd.to_datetime(df[col], errors="coerce").dropna()
    if dates.empty:
        return None
    counts = dates.dt.date.value_counts().sort_index()
    fig = go.Figure(go.Scatter(
        x=counts.index.astype(str).tolist(),
        y=counts.values.tolist(),
        mode="lines+markers",
        line=dict(color=BRAND_COLORS[1], width=2),
        marker=dict(color=BRAND_COLORS[0], size=6),
    ))
    fig.update_layout(
        title=dict(text="Medication Records by Date", font=dict(size=13, color="#003153"), x=0),
        height=320,
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False),
        **_LAYOUT_COMMON,
    )
    return fig


# ── 9. Top Indications ────────────────────────────────────────────────────────
def chart_top_indications(df: pd.DataFrame, n: int = 12) -> go.Figure:
    ind_cols = [c for c in ["Possible Indication 1", "Possible Indication 2", "Possible Indication 3"]
                if c in df.columns]
    all_ind = pd.concat([_clean(df[c]) for c in ind_cols], ignore_index=True)
    counts = all_ind.value_counts().head(n).sort_values(ascending=True)
    colors = [BRAND_COLORS[i % len(BRAND_COLORS)] for i in range(len(counts))]
    fig = go.Figure(go.Bar(
        x=counts.values,
        y=counts.index,
        orientation="h",
        marker_color=colors,
    ))
    return _bar_layout(fig, "Top Possible Indications")


# ── 10. Member Stats ──────────────────────────────────────────────────────────
def chart_member_stats(df: pd.DataFrame, n: int = 15) -> go.Figure | None:
    col = "DocID"
    if col not in df.columns:
        return None
    counts = (
        _clean(df[col])
        .value_counts()
        .head(n)
        .sort_values(ascending=True)
    )
    if counts.empty:
        return None
    colors = [BRAND_COLORS[i % len(BRAND_COLORS)] for i in range(len(counts))]
    fig = go.Figure(go.Bar(
        x=counts.values,
        y=counts.index.astype(str).tolist(),
        orientation="h",
        marker_color=colors,
    ))
    return _bar_layout(fig, "Members with Most Medications")


# ── Card wrapper HTML helpers ─────────────────────────────────────────────────
_CARD_CSS = """
<style>
.dash-card {
    background: #ffffff;
    border: 1px solid #b8ddf5;
    border-top: 3px solid #1863dc;
    border-radius: 12px;
    padding: 0.6rem 0.8rem 0.4rem 0.8rem;
    box-shadow: 6px 6px 9px rgba(24,99,220,0.09);
    margin-bottom: 0.6rem;
}
</style>
"""

def _chart_card(fig_fn, df, *args, **kwargs):
    """Render a chart inside a styled card; silently show 'Not enough data' on error."""
    st.markdown('<div class="dash-card">', unsafe_allow_html=True)
    try:
        fig = fig_fn(df, *args, **kwargs)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No data available for this chart.")
    except Exception:
        st.caption("Not enough data")
    st.markdown("</div>", unsafe_allow_html=True)


# ── Dashboard renderer ────────────────────────────────────────────────────────
def render_analytics_dashboard(df: pd.DataFrame) -> None:
    """Render the full analytics dashboard inside a Streamlit expander."""

    with st.expander("📊  Analytics Dashboard — Charts & Insights", expanded=True):
        st.markdown(_CARD_CSS, unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:0.94rem; font-weight:700; color:#003153; "
            "border-bottom:2px solid #29b6f6; padding-bottom:5px; "
            "margin:0.2rem 0 1rem 0; letter-spacing:0.2px;'>"
            "Interactive charts — hover for details, click legend to filter</div>",
            unsafe_allow_html=True,
        )

        # Row 1 — Top Medications | Top ICD Codes | HCC Distribution
        r1c1, r1c2, r1c3 = st.columns(3)
        with r1c1:
            _chart_card(chart_top_medications, df)
        with r1c2:
            _chart_card(chart_top_icd_codes, df)
        with r1c3:
            _chart_card(chart_hcc_distribution, df)

        # Row 2 — Confidence | Manual Review | HCC Flag
        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            _chart_card(chart_confidence_breakdown, df)
        with r2c2:
            _chart_card(chart_manual_review, df)
        with r2c3:
            _chart_card(chart_hcc_flag, df)

        # Row 3 — Data Source | Top Indications
        r3c1, r3c2 = st.columns(2)
        with r3c1:
            _chart_card(chart_data_source, df)
        with r3c2:
            _chart_card(chart_top_indications, df)

        # Row 4 — Date Trend (full width, conditional)
        date_fig = None
        try:
            date_fig = chart_date_trend(df)
        except Exception:
            pass
        if date_fig is not None:
            st.markdown('<div class="dash-card">', unsafe_allow_html=True)
            st.plotly_chart(date_fig, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # Row 5 — Member Stats (full width, conditional)
        member_fig = None
        try:
            member_fig = chart_member_stats(df)
        except Exception:
            pass
        if member_fig is not None:
            st.markdown('<div class="dash-card">', unsafe_allow_html=True)
            st.plotly_chart(member_fig, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
