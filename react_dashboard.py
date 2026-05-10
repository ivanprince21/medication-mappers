"""
react_dashboard.py
Renders a React + Recharts analytics dashboard inside Streamlit via
st.components.v1.html().

Key reliability choices:
  - htm (tagged-template JSX substitute, ~1 KB) instead of Babel standalone
    → no transpilation, loads instantly, works in sandboxed iframes
  - Inline CSS instead of Tailwind CDN  → zero external CSS dependency
  - Dynamic sequential script loading   → guaranteed order, visible errors
  - Version-pinned CDNs                 → no surprise breakage

Extra-credit additions:
  - Chart click → table drill-down filtering (toggle off by clicking again)
  - Top 15 ICD-10 codes bar chart
  - Drug class donut chart
  - CSV export button in table header
  - Drug class + data source + other ICD codes in table
  - Active filter badge with clear button
"""

import json
import pandas as pd
import streamlit.components.v1 as components

# ── Brand palette ─────────────────────────────────────────────────────────────
_COLORS = ["#003153", "#1863dc", "#29b6f6", "#0a4a7a",
           "#4a9fd4", "#7dc0e8", "#f0a500", "#e05c2a"]


# ─────────────────────────────────────────────────────────────────────────────
# Data aggregation
# ─────────────────────────────────────────────────────────────────────────────
def _compute_data(df: pd.DataFrame) -> dict:
    data: dict = {}
    _NULL = {"nan", "none", "nat", ""}

    def _clean(series):
        s = series.fillna("").astype(str).str.strip()
        return s[~s.str.lower().isin(_NULL)]

    # KPI
    try:
        data["kpi"] = {
            "total":          int(len(df)),
            "unique_members": int(df["DocID"].nunique()) if "DocID" in df.columns else 0,
            "manual_review":  int((df["Manual Review Flag"] == "YES").sum()) if "Manual Review Flag" in df.columns else 0,
            "high_hcc":       int(df["High Value HCC Flag"].astype(str).str.startswith("YES").sum()) if "High Value HCC Flag" in df.columns else 0,
        }
    except Exception:
        data["kpi"] = {"total": 0, "unique_members": 0, "manual_review": 0, "high_hcc": 0}

    # Confidence Level donut
    try:
        vc = _clean(df["Confidence Level"]).value_counts().reset_index()
        vc.columns = ["name", "value"]
        data["confidence"] = vc.sort_values("value", ascending=False).to_dict(orient="records")
    except Exception:
        data["confidence"] = []

    # Top 20 medications
    try:
        s = _clean(df["Normalized Generic Name"])
        s = s[~s.isin(["Unknown Medication", "Unknown"])]
        vc = s.value_counts().head(20).reset_index()
        vc.columns = ["name", "value"]
        data["top_meds"] = vc.sort_values("value", ascending=True).to_dict(orient="records")
    except Exception:
        data["top_meds"] = []

    # Manual Review pie
    try:
        vc = _clean(df["Manual Review Flag"]).value_counts().reset_index()
        vc.columns = ["name", "value"]
        data["review"] = vc.to_dict(orient="records")
    except Exception:
        data["review"] = []

    # HCC Flag bar
    try:
        vc = _clean(df["High Value HCC Flag"]).value_counts().reset_index()
        vc.columns = ["name", "value"]
        data["hcc_flags"] = vc.sort_values("value", ascending=False).to_dict(orient="records")
    except Exception:
        data["hcc_flags"] = []

    # Top 10 HCC Categories
    try:
        hcc_cols = [c for c in [f"HCC Category (ICD {i})" for i in range(1, 5)] if c in df.columns]
        if hcc_cols:
            combined = pd.concat([_clean(df[c]) for c in hcc_cols], ignore_index=True)
            combined = combined[~combined.isin(["N/A", "Not mapped"])]
            vc = combined.value_counts().head(10).reset_index()
            vc.columns = ["name", "value"]
            data["top_hcc"] = vc.sort_values("value", ascending=True).to_dict(orient="records")
        else:
            data["top_hcc"] = []
    except Exception:
        data["top_hcc"] = []

    # Top 15 ICD-10 codes (across all 4 slots)
    try:
        icd_cols  = [c for c in [f"Possible ICD-10-CM Code {i}" for i in range(1, 5)] if c in df.columns]
        desc_cols = [c for c in [f"ICD-10 Description {i}" for i in range(1, 5)] if c in df.columns]
        if icd_cols:
            all_icds = pd.concat([_clean(df[c]) for c in icd_cols], ignore_index=True)
            skip = {"n/a", "not mapped", "unknown", "none", ""}
            all_icds = all_icds[~all_icds.str.lower().isin(skip)]
            vc = all_icds.value_counts().head(15).reset_index()
            vc.columns = ["name", "value"]
            # Attach a description to each code — vectorized (no iterrows)
            code_to_desc: dict = {}
            for icd_c, desc_c in zip(icd_cols, desc_cols):
                tmp = df[[icd_c, desc_c]].copy()
                tmp.columns = ["code", "desc"]
                tmp = tmp.dropna(subset=["code", "desc"])
                tmp["code"] = tmp["code"].astype(str).str.strip()
                tmp["desc"] = tmp["desc"].astype(str).str.strip()
                tmp = tmp[~tmp["code"].str.lower().isin(skip) & (tmp["desc"] != "")]
                # setdefault equivalent: keep first desc seen per code
                for code, desc in zip(tmp["code"], tmp["desc"]):
                    code_to_desc.setdefault(code, desc)
            records = []
            for _, r in vc.iterrows():
                records.append({
                    "name":  r["name"],
                    "value": int(r["value"]),
                    "desc":  code_to_desc.get(r["name"], ""),
                })
            data["top_icd"] = sorted(records, key=lambda x: x["value"])
        else:
            data["top_icd"] = []
    except Exception:
        data["top_icd"] = []

    # Drug class donut (try multiple possible column names)
    try:
        dc_col = next(
            (c for c in df.columns if c.lower().replace(" ", "").replace("_", "") in
             {"drugclass", "drugclassification", "therapeuticclass", "class"}),
            None
        )
        if dc_col:
            vc = _clean(df[dc_col]).value_counts().head(10).reset_index()
            vc.columns = ["name", "value"]
            data["drug_class"] = vc.to_dict(orient="records")
        else:
            data["drug_class"] = []
    except Exception:
        data["drug_class"] = []

    # Date trend
    try:
        if "DateOfService" in df.columns:
            tmp = df.copy()
            tmp["_d"] = pd.to_datetime(df["DateOfService"], errors="coerce")
            tmp = tmp.dropna(subset=["_d"])
            tmp["_label"] = tmp["_d"].dt.strftime("%b %d")
            trend = (
                tmp.groupby("_label")
                   .agg(count=("_d", "count"), _sort=("_d", "min"))
                   .reset_index()
                   .sort_values("_sort")[["_label", "count"]]
                   .rename(columns={"_label": "date"})
            )
            data["date_trend"] = trend.to_dict(orient="records")
        else:
            data["date_trend"] = []
    except Exception:
        data["date_trend"] = []

    # Table (vectorized) — extended columns
    try:
        col_map = {
            "id":   "MedicationsID",
            "doc":  "DocID",
            "dos":  "DateOfService",
            "med":  "Normalized Generic Name",
            "cls":  next((c for c in df.columns if c.lower().replace(" ", "").replace("_", "") in
                          {"drugclass", "drugclassification", "therapeuticclass", "class"}), ""),
            "conf": "Confidence Level",
            "hcc":  "High Value HCC Flag",
            "rev":  "Manual Review Flag",
            "icd1": "Possible ICD-10-CM Code 1",
            "desc1":"ICD-10 Description 1",
            "icd2": "Possible ICD-10-CM Code 2",
            "icd3": "Possible ICD-10-CM Code 3",
            "icd4": "Possible ICD-10-CM Code 4",
            "src":  "Data Source",
        }
        subset = {}
        for k, col in col_map.items():
            if col and col in df.columns:
                s = df[col].fillna("").astype(str).str.strip()
                s = s.where(~s.str.lower().isin(_NULL), "")
                subset[k] = s.tolist()
            else:
                subset[k] = [""] * len(df)
        n = len(df)
        data["table"] = [{k: subset[k][i] for k in subset} for i in range(n)]
    except Exception:
        data["table"] = []

    return data


# ─────────────────────────────────────────────────────────────────────────────
# Inline CSS  (replaces Tailwind CDN)
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,system-ui,sans-serif;background:#f8fafc;color:#212121;font-size:14px}
#loading{display:flex;align-items:center;justify-content:center;height:180px;
  font-size:1rem;color:#003153;background:#eaf4fb;border-radius:12px;margin:24px;
  font-weight:600;letter-spacing:.3px}
.err{background:#fee2e2;border:1px solid #ef4444;border-radius:8px;padding:16px;
  margin:16px;color:#991b1b;font-family:monospace;white-space:pre-wrap;font-size:12px}
.header{background:linear-gradient(135deg,#003153 0%,#1863dc 100%);
  color:#fff;padding:24px 32px 20px}
.header h1{font-size:1.5rem;font-weight:800;letter-spacing:-.3px}
.header p{font-size:.85rem;opacity:.75;margin-top:4px}
.body{padding:20px 24px}
/* grid */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
/* card */
.card{background:#fff;border-radius:12px;padding:16px;
  box-shadow:0 1px 4px rgba(0,0,0,.08);border:1px solid #e5edf5}
.card-title{font-size:.75rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.5px;color:#556;margin-bottom:10px}
/* KPI */
.kpi-val{font-size:2.2rem;font-weight:900;line-height:1}
.kpi-lbl{font-size:.7rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.5px;color:#667;margin-top:4px}
/* badges */
.badge{display:inline-block;padding:2px 10px;border-radius:999px;
  font-size:.72rem;font-weight:600}
.badge-high{background:#d1fae5;color:#065f46}
.badge-med{background:#dbeafe;color:#1e3a8a}
.badge-low{background:#fef9c3;color:#92400e}
.badge-unk{background:#f3f4f6;color:#4b5563}
.badge-yes{background:#fee2e2;color:#991b1b}
.badge-no{background:#d1fae5;color:#065f46}
/* active chart filter banner */
.chart-filter-bar{background:#eff6ff;border:1px solid #1863dc;border-left:4px solid #1863dc;
  border-radius:8px;padding:8px 14px;margin-bottom:10px;
  display:flex;justify-content:space-between;align-items:center;gap:8px}
.chart-filter-label{font-size:.82rem;color:#003153;font-weight:600}
.chart-filter-hint{font-size:.75rem;color:#667;font-style:italic}
/* table */
.tbl-wrap{overflow-x:auto;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:.8rem}
thead tr{background:linear-gradient(135deg,#003153 0%,#1863dc 100%);color:#fff}
th{padding:8px 10px;text-align:left;font-size:.72rem;font-weight:600;
   text-transform:uppercase;letter-spacing:.4px;cursor:pointer;white-space:nowrap;
   user-select:none}
th:hover{background:rgba(255,255,255,.12)}
tbody tr:nth-child(even){background:#f0f7ff}
tbody tr:hover{background:#dbeafe}
td{padding:7px 10px;border-bottom:1px solid #e5edf5}
/* chart cursor pointer */
.recharts-rectangle{cursor:pointer}
.recharts-sector{cursor:pointer}
/* filter bar */
.filter-bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;align-items:center}
.filter-bar input,.filter-bar select{
  border:1px solid #c5d8ef;border-radius:999px;padding:5px 14px;
  font-size:.8rem;background:#fff;outline:none;color:#212121}
.filter-bar input{flex:1;min-width:180px}
.filter-bar input:focus,.filter-bar select:focus{border-color:#1863dc;
  box-shadow:0 0 0 2px rgba(24,99,220,.15)}
.btn{border:1px solid #c5d8ef;border-radius:999px;padding:5px 16px;
  font-size:.8rem;background:#f8fafc;cursor:pointer;color:#003153;font-weight:600}
.btn:hover{background:#eaf4fb}
.btn:disabled{opacity:.35;cursor:not-allowed}
.btn-export{background:linear-gradient(135deg,#003153,#1863dc);color:#fff;
  border:none;border-radius:999px;padding:5px 16px;
  font-size:.8rem;cursor:pointer;font-weight:600}
.btn-export:hover{background:linear-gradient(135deg,#1863dc,#29b6f6)}
.row-count{font-size:.75rem;color:#667;margin-bottom:6px}
.pagination{display:flex;justify-content:space-between;align-items:center;
  margin-top:12px}
.page-info{font-size:.75rem;color:#667}
.space-y>*+*{margin-top:16px}
.hcc-yes{color:#c2410c;font-weight:600}
.hcc-no{color:#9ca3af}
.src-tag{font-size:.7rem;background:#f0f7ff;color:#1863dc;
  padding:1px 8px;border-radius:999px;border:1px solid #c5d8ef}
.other-icds{font-family:monospace;font-size:.72rem;color:#556}
.tbl-header-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
"""

# ─────────────────────────────────────────────────────────────────────────────
# JavaScript — htm + React + Recharts (no Babel, no JSX transpilation)
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: this is a plain string — no Python f-string, so { } are literal JS
_JS_TEMPLATE = r"""
/* ── CDN loader ─────────────────────────────────────────────────────────────
   React / ReactDOM / htm are loaded sequentially (reliable CDNs, no issues).
   Recharts has historically returned 200 HTML pages instead of JS on some CDN
   paths — so we try 6 different CDN+version combinations in sequence, checking
   typeof Recharts after each attempt before moving on.
   If every Recharts URL fails we still render the KPI cards + table (no charts).
*/

var _baseCdns = [
  'https://cdn.jsdelivr.net/npm/react@18.2.0/umd/react.production.min.js',
  'https://cdn.jsdelivr.net/npm/react-dom@18.2.0/umd/react-dom.production.min.js',
];
var _htmCdn = 'https://cdn.jsdelivr.net/npm/htm@3.1.1/dist/htm.umd.js';

/* Multiple Recharts fallbacks — different CDNs and versions */
var _rechartsUrls = [
  'https://cdn.jsdelivr.net/npm/recharts@2.1.12/umd/Recharts.js',
  'https://unpkg.com/recharts@2.1.12/umd/Recharts.js',
  'https://cdn.jsdelivr.net/npm/recharts@2.5.0/umd/Recharts.js',
  'https://unpkg.com/recharts@2.5.0/umd/Recharts.js',
  'https://cdn.jsdelivr.net/npm/recharts@2.12.7/umd/Recharts.js',
  'https://unpkg.com/recharts@2.12.7/umd/Recharts.js',
];

function showErr(msg) {
  document.getElementById('root').innerHTML =
    '<div class="err"><strong>Dashboard failed to load</strong>\n\n' + msg + '</div>';
}

function loadNext(list, idx, onDone) {
  if (idx >= list.length) { onDone(); return; }
  var s = document.createElement('script');
  s.src = list[idx];
  s.onload  = function() { loadNext(list, idx + 1, onDone); };
  s.onerror = function() { showErr('Could not load CDN script:\n' + list[idx]); };
  document.head.appendChild(s);
}

/* Try each Recharts URL in order; proceed even if all fail (charts hidden) */
function loadRecharts(onDone) {
  function tryNext(idx) {
    if (idx >= _rechartsUrls.length) {
      onDone(false);   /* no Recharts — graceful degradation */
      return;
    }
    var s = document.createElement('script');
    s.src = _rechartsUrls[idx];
    s.onload = function() {
      /* small timeout so the global has a chance to be set */
      setTimeout(function() {
        if (typeof Recharts !== 'undefined') { onDone(true); }
        else { tryNext(idx + 1); }
      }, 20);
    };
    s.onerror = function() { tryNext(idx + 1); };
    document.head.appendChild(s);
  }
  tryNext(0);
}

/* Boot sequence: base CDNs → Recharts (with fallbacks) → htm → app */
loadNext(_baseCdns, 0, function() {
  loadRecharts(function(rechartsOk) {
    loadNext([_htmCdn], 0, function() {
      _bootApp(rechartsOk);
    });
  });
});

function _bootApp(rechartsOk) {
  try {
    /* Defensive globals check */
    if (typeof React === 'undefined')    { showErr('React CDN failed to load.');    return; }
    if (typeof ReactDOM === 'undefined') { showErr('ReactDOM CDN failed to load.'); return; }
    if (typeof htm === 'undefined')      { showErr('htm CDN failed to load.');      return; }

    var html = htm.bind(React.createElement);
    var useState  = React.useState;
    var useMemo   = React.useMemo;
    var RC = rechartsOk ? Recharts : null;

    var COLORS = ['#003153','#1863dc','#29b6f6','#0a4a7a','#4a9fd4','#7dc0e8','#f0a500','#e05c2a',
                  '#6366f1','#ec4899','#10b981','#f59e0b','#ef4444','#8b5cf6','#14b8a6'];
    var PAGE = 50;

    /* ── CSV export ── */
    function exportCSV(rows, filename) {
      var headers = ['DocID','Date','Generic Name','Drug Class','Confidence',
                     'HCC Flag','Manual Review','ICD-10 Code 1','Description 1',
                     'ICD-10 Code 2','ICD-10 Code 3','ICD-10 Code 4','Data Source'];
      var lines = [headers.join(',')];
      rows.forEach(function(r) {
        var vals = [r.doc,r.dos,r.med,r.cls,r.conf,r.hcc,r.rev,
                    r.icd1,r.desc1,r.icd2,r.icd3,r.icd4,r.src];
        lines.push(vals.map(function(v){
          return '"' + (v||'').replace(/"/g,'""') + '"';
        }).join(','));
      });
      var blob = new Blob([lines.join('\n')], {type:'text/csv'});
      var url  = URL.createObjectURL(blob);
      var a    = document.createElement('a');
      a.href   = url;
      a.download = filename || 'medication_results.csv';
      a.click();
      URL.revokeObjectURL(url);
    }

    /* ── KPI Card ── */
    function KPICard(p) {
      return html`
        <div class="card" style=${{ borderTop: '4px solid ' + p.color }}>
          <div class="kpi-val" style=${{ color: p.color }}>${p.value.toLocaleString()}</div>
          <div class="kpi-lbl">${p.icon} ${p.title}</div>
        </div>`;
    }

    /* ── Section Card ── */
    function Card(p) {
      return html`
        <div class="card">
          <div class="card-title">${p.title}</div>
          ${p.children}
        </div>`;
    }

    /* ── Confidence badge ── */
    function ConfBadge(p) {
      var cls = {High:'badge badge-high',Medium:'badge badge-med',
                 Low:'badge badge-low'}[p.v] || 'badge badge-unk';
      return html`<span class=${cls}>${p.v || '—'}</span>`;
    }

    /* ── Sort arrow ── */
    function Arrow(p) {
      if (p.col !== p.cur) return html`<span style=${{opacity:0.3}}> ↕</span>`;
      return html`<span> ${p.dir === 'asc' ? '↑' : '↓'}</span>`;
    }

    /* ── Custom Tooltip for ICD chart (shows description) ── */
    function IcdTooltip(p) {
      if (!p.active || !p.payload || !p.payload.length) return null;
      var entry = p.payload[0].payload;
      return html`
        <div style=${{background:'#fff',border:'1px solid #c5d8ef',borderRadius:'8px',
                      padding:'8px 12px',maxWidth:'260px',boxShadow:'0 2px 8px rgba(0,0,0,.12)'}}>
          <div style=${{fontWeight:700,color:'#003153',fontSize:'.82rem'}}>${entry.name}</div>
          ${entry.desc && html`<div style=${{fontSize:'.75rem',color:'#556',marginTop:'3px'}}>${entry.desc}</div>`}
          <div style=${{color:'#1863dc',fontWeight:600,marginTop:'4px'}}>${entry.value} records</div>
        </div>`;
    }

    /* ══ Main Dashboard ══ */
    function Dashboard(p) {
      var d = p.data;
      var kpi        = d.kpi        || {};
      var confidence = d.confidence || [];
      var topMeds    = d.top_meds   || [];
      var review     = d.review     || [];
      var hccFlags   = d.hcc_flags  || [];
      var topHcc     = d.top_hcc    || [];
      var topIcd     = d.top_icd    || [];
      var drugClass  = d.drug_class || [];
      var dateTrend  = d.date_trend || [];
      var table      = d.table      || [];

      /* ─ filter state ─ */
      var _s  = useState('');    var search      = _s[0];      var setSearch      = _s[1];
      var _fc = useState('All'); var filterConf  = _fc[0];     var setFilterConf  = _fc[1];
      var _fr = useState('All'); var filterRev   = _fr[0];     var setFilterRev   = _fr[1];
      var _fh = useState('All'); var filterHcc   = _fh[0];     var setFilterHcc   = _fh[1];
      var _sc = useState(null);  var sortCol     = _sc[0];     var setSortCol     = _sc[1];
      var _sd = useState('asc'); var sortDir     = _sd[0];     var setSortDir     = _sd[1];
      var _pg = useState(0);     var page        = _pg[0];     var setPage        = _pg[1];
      /* chart drill-down: {col, value, label} or null */
      var _cf = useState(null);  var chartFilter = _cf[0];     var setChartFilter = _cf[1];

      /* ─ chart click handlers ─ */
      function onBarClick(colName, labelPrefix) {
        return function(chartData) {
          if (!chartData || !chartData.activePayload) return;
          var val = chartData.activePayload[0].payload.name;
          if (chartFilter && chartFilter.col === colName && chartFilter.value === val) {
            setChartFilter(null); // toggle off
          } else {
            setChartFilter({col: colName, value: val,
                            label: (labelPrefix ? labelPrefix + ': ' : '') + val});
          }
          setPage(0);
        };
      }

      function onPieClick(colName, labelPrefix) {
        return function(entry) {
          if (!entry || !entry.name) return;
          if (chartFilter && chartFilter.col === colName && chartFilter.value === entry.name) {
            setChartFilter(null);
          } else {
            setChartFilter({col: colName, value: entry.name,
                            label: (labelPrefix ? labelPrefix + ': ' : '') + entry.name});
          }
          setPage(0);
        };
      }

      /* ─ hcc filter options ─ */
      var hccOpts = useMemo(function() {
        var vals = {};
        table.forEach(function(r){ if(r.hcc) vals[r.hcc]=1; });
        return Object.keys(vals).sort();
      }, [table]);

      /* ─ sort handler ─ */
      function handleSort(col) {
        if (sortCol === col) { setSortDir(function(d){ return d==='asc'?'desc':'asc'; }); }
        else { setSortCol(col); setSortDir('asc'); }
        setPage(0);
      }

      /* ─ clear all filters ─ */
      function clearFilters() {
        setSearch(''); setFilterConf('All'); setFilterRev('All');
        setFilterHcc('All'); setChartFilter(null); setPage(0);
      }

      /* ─ filtered + sorted rows ─ */
      var filtered = useMemo(function() {
        var rows = table;
        /* text search */
        var q = search.toLowerCase();
        if (q) rows = rows.filter(function(r){
          return (r.med||'').toLowerCase().includes(q)  ||
                 (r.icd1||'').toLowerCase().includes(q) ||
                 (r.desc1||'').toLowerCase().includes(q)||
                 (r.doc||'').toLowerCase().includes(q)  ||
                 (r.cls||'').toLowerCase().includes(q);
        });
        /* dropdown filters */
        if (filterConf !== 'All') rows = rows.filter(function(r){ return r.conf === filterConf; });
        if (filterRev  !== 'All') rows = rows.filter(function(r){ return r.rev  === filterRev;  });
        if (filterHcc  !== 'All') rows = rows.filter(function(r){ return r.hcc  === filterHcc;  });
        /* chart drill-down */
        if (chartFilter) {
          var col = chartFilter.col;
          var val = (chartFilter.value || '').toLowerCase();
          if (col === 'icd_any') {
            rows = rows.filter(function(r){
              return (r.icd1||'').toLowerCase() === val ||
                     (r.icd2||'').toLowerCase() === val ||
                     (r.icd3||'').toLowerCase() === val ||
                     (r.icd4||'').toLowerCase() === val;
            });
          } else {
            rows = rows.filter(function(r){
              return (r[col]||'').toLowerCase() === val;
            });
          }
        }
        /* sort */
        if (sortCol) {
          var dir = sortDir;
          rows = rows.slice().sort(function(a,b){
            var cmp = String(a[sortCol]||'').localeCompare(String(b[sortCol]||''));
            return dir === 'asc' ? cmp : -cmp;
          });
        }
        return rows;
      }, [table, search, filterConf, filterRev, filterHcc, chartFilter, sortCol, sortDir]);

      var totalPages = Math.max(1, Math.ceil(filtered.length / PAGE));
      var pageRows   = filtered.slice(page * PAGE, (page+1) * PAGE);

      /* ─ pie label ─ */
      var totalRev = review.reduce(function(s,r){ return s+r.value; }, 0) || 1;
      var pctLabel = function(entry) {
        return entry.name + ': ' + ((entry.value/totalRev)*100).toFixed(0) + '%';
      };

      /* ─ active bar highlight helper ─ */
      function barFill(col, name, defaultColor) {
        if (!chartFilter || chartFilter.col !== col) return defaultColor;
        return chartFilter.value === name ? defaultColor : 'rgba(0,0,0,.15)';
      }

      return html`
        <div>

          <!-- Header -->
          <div class="header">
            <h1>📊 Medication Analytics Dashboard</h1>
            <p>Interactive post-processing insights — click any chart bar or slice to drill down</p>
          </div>

          <div class="body space-y">

            <!-- Charts unavailable banner (shown only when Recharts CDN failed) -->
            ${!RC && html`
              <div style=${{background:'#fff8e1',border:'1px solid #f0a500',borderLeft:'4px solid #f0a500',
                            borderRadius:'8px',padding:'10px 16px',fontSize:'.82rem',color:'#5d4037'}}>
                ⚠️ <strong>Charts could not load</strong> — Recharts CDN unavailable (tried 6 URLs).
                KPI summary and data table are fully functional.
                <span style=${{marginLeft:'8px'}}>
                  <a href="javascript:location.reload()" style=${{color:'#1863dc',fontWeight:600}}>
                    Click here to retry
                  </a>
                </span>
              </div>
            `}

            <!-- KPI Row -->
            <div class="grid4">
              <${KPICard} title="Total Records"          value=${kpi.total||0}          color="#003153" icon="📋" />
              <${KPICard} title="Unique Members"         value=${kpi.unique_members||0}  color="#1863dc" icon="👥" />
              <${KPICard} title="Manual Review Required" value=${kpi.manual_review||0}   color="#f0a500" icon="⚠️" />
              <${KPICard} title="High Value HCC Flagged" value=${kpi.high_hcc||0}        color="#e05c2a" icon="🏷️" />
            </div>

            <!-- Charts (rows 1-4) — only rendered when Recharts CDN loaded -->
            <!-- Row 1: Confidence | Manual Review | HCC Flag -->
            ${RC && html`<div class="grid3">

              <${Card} title="Confidence Level — click to filter">
                <${RC.ResponsiveContainer} width="100%" height=${220}>
                  <${RC.PieChart}>
                    <${RC.Pie} data=${confidence} dataKey="value" nameKey="name"
                      innerRadius=${55} outerRadius=${85} paddingAngle=${3}
                      onClick=${onPieClick('conf', 'Confidence')}>
                      ${confidence.map(function(e,i){
                        var active = !chartFilter || (chartFilter.col==='conf' && chartFilter.value===e.name);
                        return html`<${RC.Cell} key=${e.name} fill=${COLORS[i%COLORS.length]}
                          opacity=${active ? 1 : 0.25} />`;
                      })}
                    <//>
                    <${RC.Tooltip} />
                    <${RC.Legend} iconSize=${10} wrapperStyle=${{fontSize:'11px'}} />
                  <//>
                <//>
              <//>

              <${Card} title="Manual Review Flag — click to filter">
                <${RC.ResponsiveContainer} width="100%" height=${220}>
                  <${RC.PieChart}>
                    <${RC.Pie} data=${review} dataKey="value" nameKey="name"
                      outerRadius=${85} label=${pctLabel} paddingAngle=${3}
                      onClick=${onPieClick('rev', 'Review')}>
                      ${review.map(function(e,i){
                        var active = !chartFilter || (chartFilter.col==='rev' && chartFilter.value===e.name);
                        return html`<${RC.Cell} key=${e.name} fill=${COLORS[i%COLORS.length]}
                          opacity=${active ? 1 : 0.25} />`;
                      })}
                    <//>
                    <${RC.Tooltip} />
                    <${RC.Legend} iconSize=${10} wrapperStyle=${{fontSize:'11px'}} />
                  <//>
                <//>
              <//>

              <${Card} title="High Value HCC Flags — click to filter">
                <${RC.ResponsiveContainer} width="100%" height=${220}>
                  <${RC.BarChart} data=${hccFlags} margin=${{top:5,right:8,left:0,bottom:40}}
                    onClick=${onBarClick('hcc', 'HCC Flag')}>
                    <${RC.CartesianGrid} strokeDasharray="3 3" vertical=${false} />
                    <${RC.XAxis} dataKey="name" tick=${{fontSize:9,angle:-15,textAnchor:'end'}} interval=${0} />
                    <${RC.YAxis} tick=${{fontSize:10}} />
                    <${RC.Tooltip} />
                    <${RC.Bar} dataKey="value" radius=${[3,3,0,0]}>
                      ${hccFlags.map(function(e){
                        return html`<${RC.Cell} key=${e.name}
                          fill=${barFill('hcc', e.name, '#1863dc')} />`;
                      })}
                    <//>
                  <//>
                <//>
              <//>

            </div>`}

            ${RC && html`<div class="grid2">

              <${Card} title="Top 20 Medications — click bar to filter">
                <${RC.ResponsiveContainer} width="100%" height=${420}>
                  <${RC.BarChart} layout="vertical" data=${topMeds}
                    margin=${{top:0,right:20,left:0,bottom:0}}
                    onClick=${onBarClick('med', 'Medication')}>
                    <${RC.CartesianGrid} strokeDasharray="3 3" horizontal=${false} />
                    <${RC.XAxis} type="number" tick=${{fontSize:10}} />
                    <${RC.YAxis} type="category" dataKey="name" width=${155} tick=${{fontSize:11}} />
                    <${RC.Tooltip} />
                    <${RC.Bar} dataKey="value" radius=${[0,3,3,0]}>
                      ${topMeds.map(function(e){
                        return html`<${RC.Cell} key=${e.name}
                          fill=${barFill('med', e.name, '#003153')} />`;
                      })}
                    <//>
                  <//>
                <//>
              <//>

              <${Card} title="Top 10 HCC Category Combinations">
                <${RC.ResponsiveContainer} width="100%" height=${420}>
                  <${RC.BarChart} layout="vertical" data=${topHcc}
                    margin=${{top:0,right:20,left:0,bottom:0}}>
                    <${RC.CartesianGrid} strokeDasharray="3 3" horizontal=${false} />
                    <${RC.XAxis} type="number" tick=${{fontSize:10}} />
                    <${RC.YAxis} type="category" dataKey="name" width=${165} tick=${{fontSize:11}} />
                    <${RC.Tooltip} />
                    <${RC.Bar} dataKey="value" fill="#29b6f6" radius=${[0,3,3,0]} />
                  <//>
                <//>
              <//>

            </div>`}

            ${RC && html`<div class="grid2">

              <${Card} title="Top 15 ICD-10-CM Codes — click bar to filter">
                ${topIcd.length === 0
                  ? html`<div style=${{color:'#9ca3af',fontSize:'.8rem',padding:'20px 0',textAlign:'center'}}>No ICD-10 codes in results</div>`
                  : html`
                  <${RC.ResponsiveContainer} width="100%" height=${400}>
                    <${RC.BarChart} layout="vertical" data=${topIcd}
                      margin=${{top:0,right:20,left:0,bottom:0}}
                      onClick=${onBarClick('icd_any', 'ICD-10')}>
                      <${RC.CartesianGrid} strokeDasharray="3 3" horizontal=${false} />
                      <${RC.XAxis} type="number" tick=${{fontSize:10}} />
                      <${RC.YAxis} type="category" dataKey="name" width=${80} tick=${{fontSize:11,fontFamily:'monospace'}} />
                      <${RC.Tooltip} content=${html`<${IcdTooltip} />`} />
                      <${RC.Bar} dataKey="value" radius=${[0,3,3,0]}>
                        ${topIcd.map(function(e){
                          return html`<${RC.Cell} key=${e.name}
                            fill=${barFill('icd_any', e.name, '#4a9fd4')} />`;
                        })}
                      <//>
                    <//>
                  <//>
                `}
              <//>

              <${Card} title=${drugClass.length > 0 ? 'Drug Class Distribution — click to filter' : 'Drug Class Distribution'}>
                ${drugClass.length === 0
                  ? html`<div style=${{color:'#9ca3af',fontSize:'.8rem',padding:'20px 0',textAlign:'center'}}>No drug class data in results</div>`
                  : html`
                  <${RC.ResponsiveContainer} width="100%" height=${400}>
                    <${RC.PieChart}>
                      <${RC.Pie} data=${drugClass} dataKey="value" nameKey="name"
                        innerRadius=${60} outerRadius=${130} paddingAngle=${2}
                        onClick=${onPieClick('cls', 'Drug Class')}>
                        ${drugClass.map(function(e,i){
                          var active = !chartFilter || (chartFilter.col==='cls' && chartFilter.value===e.name);
                          return html`<${RC.Cell} key=${e.name} fill=${COLORS[i%COLORS.length]}
                            opacity=${active ? 1 : 0.25} />`;
                        })}
                      <//>
                      <${RC.Tooltip} />
                      <${RC.Legend} iconSize=${10} wrapperStyle=${{fontSize:'11px'}} />
                    <//>
                  <//>
                `}
              <//>

            </div>`}

            ${RC && html`<${Card} title="Record Count by Date of Service">
              <${RC.ResponsiveContainer} width="100%" height=${220}>
                <${RC.LineChart} data=${dateTrend} margin=${{top:5,right:20,left:0,bottom:40}}>
                  <${RC.CartesianGrid} strokeDasharray="3 3" />
                  <${RC.XAxis} dataKey="date" tick=${{fontSize:10,angle:-30,textAnchor:'end'}}
                    interval="preserveStartEnd" />
                  <${RC.YAxis} tick=${{fontSize:10}} />
                  <${RC.Tooltip} />
                  <${RC.Line} type="monotone" dataKey="count"
                    stroke="#1863dc" strokeWidth=${2} dot=${false} />
                <//>
              <//>
            <//>
            `}

            <!-- Data Table -->
            <${Card} title="Detailed Records — Filterable, Sortable & Exportable">

              <!-- Active chart filter banner -->
              ${chartFilter && html`
                <div class="chart-filter-bar">
                  <div>
                    <span class="chart-filter-label">🔍 Chart filter active: </span>
                    <span class="badge badge-med" style=${{marginLeft:'6px'}}>${chartFilter.label}</span>
                    <span class="chart-filter-hint" style=${{marginLeft:'10px'}}>
                      Click the same chart element again to remove
                    </span>
                  </div>
                  <button class="btn" style=${{padding:'3px 12px',fontSize:'.75rem'}}
                    onClick=${function(){ setChartFilter(null); setPage(0); }}>
                    ✕ Clear
                  </button>
                </div>
              `}

              <!-- Filter bar -->
              <div class="filter-bar">
                <input type="text" placeholder="🔍 Search name, ICD, description, DocID, drug class…"
                  value=${search}
                  onInput=${function(e){ setSearch(e.target.value); setPage(0); }} />
                <select value=${filterConf}
                  onChange=${function(e){ setFilterConf(e.target.value); setPage(0); }}>
                  <option value="All">All Confidence</option>
                  <option>High</option><option>Medium</option>
                  <option>Low</option><option>Unknown</option>
                </select>
                <select value=${filterRev}
                  onChange=${function(e){ setFilterRev(e.target.value); setPage(0); }}>
                  <option value="All">All Review</option>
                  <option>YES</option><option>No</option>
                </select>
                <select value=${filterHcc}
                  onChange=${function(e){ setFilterHcc(e.target.value); setPage(0); }}>
                  <option value="All">All HCC Flags</option>
                  ${hccOpts.map(function(v){
                    return html`<option key=${v} value=${v}>${v}</option>`;
                  })}
                </select>
                <button class="btn" onClick=${clearFilters}>✕ Clear All</button>
              </div>

              <!-- Row count + export -->
              <div class="tbl-header-row">
                <div class="row-count">
                  Showing ${pageRows.length} of ${filtered.length} records
                  (${table.length} total)
                </div>
                <button class="btn-export"
                  onClick=${function(){ exportCSV(filtered, 'medication_results_filtered.csv'); }}>
                  ⬇ Export CSV (${filtered.length} rows)
                </button>
              </div>

              <div class="tbl-wrap">
                <table>
                  <thead>
                    <tr>
                      ${[['doc','DocID'],['dos','Date'],['med','Generic Name'],
                         ['cls','Drug Class'],['conf','Confidence'],
                         ['hcc','HCC Flag'],['rev','Manual Review'],
                         ['icd1','ICD-10 Code'],['desc1','Description'],
                         ['src','Source']].map(function(c){
                        return html`
                          <th key=${c[0]} onClick=${function(){ handleSort(c[0]); }}>
                            ${c[1]}<${Arrow} col=${c[0]} cur=${sortCol} dir=${sortDir} />
                          </th>`;
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    ${pageRows.map(function(row, i){
                      var otherIcds = [row.icd2, row.icd3, row.icd4]
                        .filter(function(x){ return x && x.trim(); })
                        .join(', ');
                      return html`
                        <tr key=${i}>
                          <td style=${{fontWeight:600}}>${row.doc}</td>
                          <td style=${{whiteSpace:'nowrap'}}>${row.dos}</td>
                          <td style=${{fontWeight:500}}>
                            ${row.med}
                            ${otherIcds && html`
                              <div class="other-icds" title=${otherIcds}>
                                + ${otherIcds}
                              </div>`}
                          </td>
                          <td style=${{fontSize:'.75rem',color:'#667'}}>${row.cls || '—'}</td>
                          <td><${ConfBadge} v=${row.conf} /></td>
                          <td class=${row.hcc&&row.hcc.startsWith('YES')?'hcc-yes':'hcc-no'}>
                            ${row.hcc}
                          </td>
                          <td>
                            ${row.rev==='YES'
                              ? html`<span class="badge badge-yes">YES</span>`
                              : row.rev==='No'
                              ? html`<span class="badge badge-no">No</span>`
                              : html`<span style=${{color:'#9ca3af'}}>${row.rev}</span>`}
                          </td>
                          <td style=${{fontFamily:'monospace',fontSize:'.78rem'}}>${row.icd1}</td>
                          <td style=${{maxWidth:'200px',whiteSpace:'nowrap',overflow:'hidden',
                               textOverflow:'ellipsis'}} title=${row.desc1}>${row.desc1}</td>
                          <td>
                            ${row.src && html`<span class="src-tag">${row.src.replace(' (lookup)', '')}</span>`}
                          </td>
                        </tr>`;
                    })}
                    ${pageRows.length===0 && html`
                      <tr><td colSpan=${10}
                        style=${{textAlign:'center',padding:'32px',color:'#9ca3af'}}>
                        No records match your filters.
                      </td></tr>`}
                  </tbody>
                </table>
              </div>

              <div class="pagination">
                <button class="btn" disabled=${page===0}
                  onClick=${function(){ setPage(function(p){ return Math.max(0,p-1); }); }}>
                  ← Prev
                </button>
                <span class="page-info">
                  Page ${page+1} of ${totalPages} · ${filtered.length} records
                </span>
                <button class="btn" disabled=${page>=totalPages-1}
                  onClick=${function(){ setPage(function(p){ return Math.min(totalPages-1,p+1); }); }}>
                  Next →
                </button>
              </div>

            <//>

          </div>
        </div>`;
    }

    /* ── Boot ── */
    ReactDOM.createRoot(document.getElementById('root'))
      .render(html`<${Dashboard} data=${window.__DATA__} />`);

  } catch(e) {
    showErr(e.toString() + '\n\nStack:\n' + (e.stack||''));
  }
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# HTML builder
# ─────────────────────────────────────────────────────────────────────────────
def _build_html(data: dict) -> str:
    try:
        data_json = json.dumps(data, ensure_ascii=False, default=str)
        # Replace < so any </script> variant (any case) cannot break the inline <script> block
        data_json = data_json.replace("<", r"\u003c")

        return (
            "<!DOCTYPE html><html lang='en'><head>"
            "<meta charset='UTF-8'>"
            "<style>" + _CSS + "</style>"
            "<script>window.__DATA__ = " + data_json + ";</script>"
            "</head><body>"
            "<div id='root'><div id='loading'>⏳ Loading analytics dashboard…</div></div>"
            "<script>" + _JS_TEMPLATE + "</script>"
            "</body></html>"
        )
    except Exception as e:
        return (
            "<!DOCTYPE html><html><body>"
            "<div class='err'><strong>Build error:</strong><br>" + str(e) + "</div>"
            "</body></html>"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def render_react_dashboard(df: pd.DataFrame) -> None:
    """Render the React analytics dashboard from the processed results DataFrame."""
    data = _compute_data(df)
    html_str = _build_html(data)
    components.html(html_str, height=3400, scrolling=True)
