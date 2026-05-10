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
    counts = _clean(df.get(col, pd.Series(dtype=str))).value_counts()
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

def _chart_card(fig_fn, df, chart_key: str, filter_cols: list[str],
                point_attr: str = "y", *args, **kwargs):
    """
    Render a chart card with drill-down support.

    Clicking a bar or pie slice stores a drill-down filter in
    st.session_state["drill_filter"] which the results table reads.

    Args:
        fig_fn      : chart function to call
        df          : results DataFrame
        chart_key   : unique Streamlit key for this chart
        filter_cols : DataFrame columns to match when this chart is clicked
        point_attr  : "y" for horizontal bars, "label" for pie/donut,
                      "x" for line/date charts
    """
    st.markdown('<div class="dash-card">', unsafe_allow_html=True)
    try:
        fig = fig_fn(df, *args, **kwargs)
        if fig is not None:
            is_active = (
                st.session_state.get("drill_filter", {}).get("source_chart") == chart_key
            )
            if is_active:
                active_val = st.session_state["drill_filter"]["value"]
                st.markdown(
                    f"<div style='font-size:0.72rem; color:#1863dc; font-weight:600; "
                    f"margin-bottom:4px;'>🔍 Filtered: <em>{active_val}</em></div>",
                    unsafe_allow_html=True,
                )
            try:
                event = st.plotly_chart(
                    fig,
                    use_container_width=True,
                    on_select="rerun",
                    key=chart_key,
                )
                if event and hasattr(event, "selection") and event.selection.points:
                    pt  = event.selection.points[0]
                    val = pt.get(point_attr) or pt.get("y") or pt.get("label")
                    if val is not None:
                        val = str(val).strip()
                        existing = st.session_state.get("drill_filter", {})
                        # Toggle off if same chart + same value clicked again
                        if (existing.get("source_chart") == chart_key
                                and existing.get("value") == val):
                            st.session_state.pop("drill_filter", None)
                        else:
                            st.session_state["drill_filter"] = {
                                "value":        val,
                                "columns":      filter_cols,
                                "source_chart": chart_key,
                                "label":        f"{fig_fn.__name__.replace('chart_','').replace('_',' ').title()}: {val}",
                            }
                        st.rerun()
            except TypeError:
                # Streamlit < 1.35 — render without drill-down
                st.plotly_chart(fig, use_container_width=True, key=chart_key)
        else:
            st.caption("No data available for this chart.")
    except Exception:
        st.caption("Not enough data")
    st.markdown("</div>", unsafe_allow_html=True)


def _full_width_card(fig, chart_key: str, filter_cols: list[str],
                     point_attr: str = "x"):
    """Full-width version of _chart_card for date trend and member stats."""
    st.markdown('<div class="dash-card">', unsafe_allow_html=True)
    is_active = st.session_state.get("drill_filter", {}).get("source_chart") == chart_key
    if is_active:
        active_val = st.session_state["drill_filter"]["value"]
        st.markdown(
            f"<div style='font-size:0.72rem; color:#1863dc; font-weight:600; "
            f"margin-bottom:4px;'>🔍 Filtered: <em>{active_val}</em></div>",
            unsafe_allow_html=True,
        )
    try:
        event = st.plotly_chart(fig, use_container_width=True,
                                on_select="rerun", key=chart_key)
        if event and hasattr(event, "selection") and event.selection.points:
            pt  = event.selection.points[0]
            val = pt.get(point_attr) or pt.get("y") or pt.get("label")
            if val is not None:
                val = str(val).strip()
                existing = st.session_state.get("drill_filter", {})
                if (existing.get("source_chart") == chart_key
                        and existing.get("value") == val):
                    st.session_state.pop("drill_filter", None)
                else:
                    st.session_state["drill_filter"] = {
                        "value":        val,
                        "columns":      filter_cols,
                        "source_chart": chart_key,
                        "label":        f"{chart_key.replace('drill_','').replace('_',' ').title()}: {val}",
                    }
                st.rerun()
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=chart_key)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Dashboard renderer ────────────────────────────────────────────────────────
def render_analytics_dashboard(df: pd.DataFrame) -> None:
    """Render the full analytics dashboard inside a Streamlit expander."""

    ICD_COLS = [f"Possible ICD-10-CM Code {i}" for i in range(1, 5)]
    HCC_COLS = [f"HCC Category (ICD {i})" for i in range(1, 5)]
    IND_COLS = [f"Possible Indication {i}" for i in range(1, 4)]

    with st.expander("📊  Analytics Dashboard — Charts & Insights", expanded=True):
        st.markdown(_CARD_CSS, unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:0.94rem; font-weight:700; color:#003153; "
            "border-bottom:2px solid #29b6f6; padding-bottom:5px; "
            "margin:0.2rem 0 1rem 0; letter-spacing:0.2px;'>"
            "Click any bar or slice to drill down into the results table below</div>",
            unsafe_allow_html=True,
        )

        # Row 1 — Top Medications | Top ICD Codes | HCC Distribution
        r1c1, r1c2, r1c3 = st.columns(3)
        with r1c1:
            _chart_card(chart_top_medications, df,
                        "drill_medications", ["Normalized Generic Name"], "y")
        with r1c2:
            _chart_card(chart_top_icd_codes, df,
                        "drill_icd", ICD_COLS, "y")
        with r1c3:
            _chart_card(chart_hcc_distribution, df,
                        "drill_hcc_dist", HCC_COLS, "y")

        # Row 2 — Confidence | Manual Review | HCC Flag
        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            _chart_card(chart_confidence_breakdown, df,
                        "drill_confidence", ["Confidence Level"], "label")
        with r2c2:
            _chart_card(chart_manual_review, df,
                        "drill_review", ["Manual Review Flag"], "label")
        with r2c3:
            _chart_card(chart_hcc_flag, df,
                        "drill_hcc_flag", ["High Value HCC Flag"], "label")

        # Row 3 — Data Source | Top Indications
        r3c1, r3c2 = st.columns(2)
        with r3c1:
            _chart_card(chart_data_source, df,
                        "drill_source", ["Data Source"], "y")
        with r3c2:
            _chart_card(chart_top_indications, df,
                        "drill_indications", IND_COLS, "y")

        # Row 4 — Date Trend (full width, conditional)
        try:
            date_fig = chart_date_trend(df)
            if date_fig is not None:
                _full_width_card(date_fig, "drill_date", ["DateOfService"], "x")
        except Exception:
            pass

        # Row 5 — Member Stats (full width, conditional)
        try:
            member_fig = chart_member_stats(df)
            if member_fig is not None:
                _full_width_card(member_fig, "drill_member", ["DocID"], "y")
        except Exception:
            pass
