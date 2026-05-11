"""
react_dashboard.py
Renders an analytics dashboard inside Streamlit via st.components.v1.html().

Stack:
  - React 18  + htm  → table, filters, KPI cards (no Babel, no transpilation)
  - Chart.js 4       → all charts (canvas-based, no shadow-DOM issues)

Why Chart.js instead of Recharts:
  Recharts UMD CDNs silently return 200 HTML pages in Streamlit iframes,
  so typeof Recharts is never defined. Chart.js CDN is rock-solid and the
  library is 90 KB vs 400 KB for Recharts.
"""

import json
import pandas as pd
import streamlit.components.v1 as components


# ─────────────────────────────────────────────────────────────────────────────
# Data aggregation  (Python — unchanged)
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
            combined = combined[~combined.isin(["N/A", "Not mapped", "No HCC", ""])]
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
            # Attach descriptions — vectorized
            code_to_desc: dict = {}
            for icd_c, desc_c in zip(icd_cols, desc_cols):
                tmp = df[[icd_c, desc_c]].copy()
                tmp.columns = ["code", "desc"]
                tmp = tmp.dropna(subset=["code", "desc"])
                tmp["code"] = tmp["code"].astype(str).str.strip()
                tmp["desc"] = tmp["desc"].astype(str).str.strip()
                tmp = tmp[~tmp["code"].str.lower().isin(skip) & (tmp["desc"] != "")]
                for code, desc in zip(tmp["code"], tmp["desc"]):
                    code_to_desc.setdefault(code, desc)
            records = []
            for _, r in vc.iterrows():
                records.append({"name": r["name"], "value": int(r["value"]),
                                 "desc": code_to_desc.get(r["name"], "")})
            data["top_icd"] = sorted(records, key=lambda x: x["value"])
        else:
            data["top_icd"] = []
    except Exception:
        data["top_icd"] = []

    # Drug class donut
    try:
        dc_col = next(
            (c for c in df.columns if c.lower().replace(" ", "").replace("_", "") in
             {"drugclass", "drugclassification", "therapeuticclass", "class"}), None)
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

    # Table (vectorized)
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
            "desc1": "ICD-10 Description 1",
            "icd2": "Possible ICD-10-CM Code 2",
            "icd3": "Possible ICD-10-CM Code 3",
            "icd4": "Possible ICD-10-CM Code 4",
            "src":  "Data Source",
            # HCC category slots — used by the Top 10 HCC chart drill-down filter
            "hcc1": "HCC Category (ICD 1)",
            "hcc2": "HCC Category (ICD 2)",
            "hcc3": "HCC Category (ICD 3)",
            "hcc4": "HCC Category (ICD 4)",
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
# Inline CSS
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,system-ui,sans-serif;background:#ffffff;color:#212121;font-size:14px}
#loading{display:flex;align-items:center;justify-content:center;height:180px;
  font-size:1rem;color:#003153;background:linear-gradient(135deg,#f0f7ff,#eaf4fb);
  border-radius:12px;margin:24px;font-weight:600;letter-spacing:.3px;
  box-shadow:0 4px 20px rgba(24,99,220,0.08)}
.err{background:#fee2e2;border:1px solid #ef4444;border-radius:8px;padding:16px;
  margin:16px;color:#991b1b;font-family:monospace;white-space:pre-wrap;font-size:12px}
.header{background:linear-gradient(135deg,#003153 0%,#1863dc 100%);
  color:#fff;padding:24px 32px 20px;
  box-shadow:0 4px 20px rgba(24,99,220,0.25)}
.header h1{font-size:1.5rem;font-weight:800;letter-spacing:-.3px}
.header p{font-size:.85rem;opacity:.75;margin-top:4px}
.body{padding:20px 24px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.card{background:linear-gradient(135deg,#ffffff 0%,#f8fbff 100%);border-radius:12px;padding:16px;
  box-shadow:0 2px 16px rgba(24,99,220,0.07),0 1px 3px rgba(0,0,0,0.04);
  border:1px solid #e2eef8;transition:box-shadow 0.2s ease,transform 0.2s ease}
.card:hover{box-shadow:0 4px 24px rgba(24,99,220,0.12),0 1px 4px rgba(0,0,0,0.06);transform:translateY(-1px)}
.card-title{font-size:.72rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.5px;color:#6b7a8d;margin-bottom:10px}
.kpi-val{font-size:2.2rem;font-weight:900;line-height:1}
.kpi-lbl{font-size:.7rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.5px;color:#667;margin-top:4px}
.badge{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.72rem;font-weight:600}
.badge-high{background:linear-gradient(135deg,#d1fae5,#ecfdf5);color:#065f46}
.badge-med{background:linear-gradient(135deg,#dbeafe,#eff6ff);color:#1e3a8a}
.badge-low{background:linear-gradient(135deg,#fef9c3,#fefce8);color:#92400e}
.badge-unk{background:linear-gradient(135deg,#f3f4f6,#f9fafb);color:#4b5563}
.badge-yes{background:linear-gradient(135deg,#fee2e2,#fff5f5);color:#991b1b}
.badge-no{background:linear-gradient(135deg,#d1fae5,#ecfdf5);color:#065f46}
.chart-filter-bar{background:linear-gradient(135deg,#eff6ff,#f0f7ff);
  border:1px solid #bfdbfe;border-left:3px solid #1863dc;
  border-radius:10px;padding:8px 14px;margin-bottom:10px;
  display:flex;justify-content:space-between;align-items:center;gap:8px;
  box-shadow:0 2px 8px rgba(24,99,220,0.08)}
.chart-filter-label{font-size:.82rem;color:#003153;font-weight:600}
.chart-filter-hint{font-size:.75rem;color:#667;font-style:italic}
.tbl-wrap{overflow-x:auto;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:.8rem}
thead tr{background:linear-gradient(135deg,#003153 0%,#1863dc 100%);color:#fff}
th{padding:7px 12px;text-align:left;font-size:.72rem;font-weight:600;
   text-transform:uppercase;letter-spacing:.4px;cursor:pointer;white-space:nowrap;user-select:none}
th:hover{background:rgba(255,255,255,.12)}
tbody tr:nth-child(even){background:#f8faff}
tbody tr:hover{background:linear-gradient(135deg,#eff6ff,#f0f7ff)}
td{padding:7px 10px;border-bottom:1px solid #eef2f8}
.filter-bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;align-items:center}
.filter-bar input,.filter-bar select{border:1px solid #d0dff0;border-radius:10px;
  padding:5px 14px;font-size:.8rem;background:#fff;outline:none;color:#212121;
  box-shadow:0 1px 4px rgba(24,99,220,0.06)}
.filter-bar input{flex:1;min-width:180px}
.filter-bar input:focus,.filter-bar select:focus{border-color:#1863dc;
  box-shadow:0 0 0 3px rgba(24,99,220,.12)}
.btn{border:1px solid #d0dff0;border-radius:999px;padding:5px 16px;
  font-size:.8rem;background:linear-gradient(135deg,#f8fafc,#f0f7ff);
  cursor:pointer;color:#003153;font-weight:600;
  box-shadow:0 1px 4px rgba(24,99,220,0.06);transition:all 0.15s ease}
.btn:hover{background:linear-gradient(135deg,#eaf4fb,#e0f0ff);
  box-shadow:0 2px 8px rgba(24,99,220,0.12)}
.btn:disabled{opacity:.35;cursor:not-allowed}
.btn-export{background:linear-gradient(135deg,#003153,#1863dc);color:#fff;border:none;
  border-radius:999px;padding:5px 16px;font-size:.8rem;cursor:pointer;font-weight:600;
  box-shadow:0 4px 16px rgba(24,99,220,0.30);transition:all 0.2s ease}
.btn-export:hover{background:linear-gradient(135deg,#1863dc,#29b6f6);
  box-shadow:0 4px 20px rgba(41,182,246,0.40);transform:translateY(-1px)}
.row-count{font-size:.75rem;color:#667;margin-bottom:6px}
.pagination{display:flex;justify-content:space-between;align-items:center;margin-top:12px}
.page-info{font-size:.75rem;color:#667}
.space-y>*+*{margin-top:14px}
.hcc-yes{color:#c2410c;font-weight:600}
.hcc-no{color:#9ca3af}
.src-tag{font-size:.7rem;background:linear-gradient(135deg,#f0f7ff,#eaf4fb);color:#1863dc;
  padding:2px 9px;border-radius:999px;border:1px solid #c5d8ef}
.other-icds{font-family:monospace;font-size:.72rem;color:#556}
.tbl-header-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.no-chart{color:#9ca3af;text-align:center;padding:20px;font-size:.8rem}
"""

# ─────────────────────────────────────────────────────────────────────────────
# JavaScript — React 18 + htm + Chart.js  (plain string, NOT f-string)
# ─────────────────────────────────────────────────────────────────────────────
_JS_TEMPLATE = r"""
/* ── CDN list ─────────────────────────────────────────────────────────────── */
var _baseCdns = [
  'https://cdn.jsdelivr.net/npm/react@18.2.0/umd/react.production.min.js',
  'https://cdn.jsdelivr.net/npm/react-dom@18.2.0/umd/react-dom.production.min.js',
];
var _htmCdn = 'https://cdn.jsdelivr.net/npm/htm@3.1.1/dist/htm.umd.js';

/* Chart.js — multiple CDN + version fallbacks */
var _cjsUrls = [
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
  'https://unpkg.com/chart.js@4.4.0/dist/chart.umd.min.js',
  'https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js',
  'https://unpkg.com/chart.js@3.9.1/dist/chart.min.js',
];

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function showErr(msg) {
  document.getElementById('root').innerHTML =
    '<div class="err"><strong>Dashboard error</strong>\n\n' + msg + '</div>';
}

function loadNext(list, idx, onDone) {
  if (idx >= list.length) { onDone(); return; }
  var s = document.createElement('script');
  s.src = list[idx];
  s.onload  = function() { loadNext(list, idx + 1, onDone); };
  s.onerror = function() { showErr('CDN load failed:\n' + list[idx]); };
  document.head.appendChild(s);
}

function loadChartJs(onDone) {
  function tryNext(idx) {
    if (idx >= _cjsUrls.length) { onDone(false); return; }
    var s = document.createElement('script');
    s.src = _cjsUrls[idx];
    s.onload = function() {
      setTimeout(function() {
        if (typeof Chart !== 'undefined') { onDone(true); }
        else { tryNext(idx + 1); }
      }, 30);
    };
    s.onerror = function() { tryNext(idx + 1); };
    document.head.appendChild(s);
  }
  tryNext(0);
}

/* ── Boot sequence ───────────────────────────────────────────────────────── */
loadNext(_baseCdns, 0, function() {
  loadChartJs(function(cjOk) {
    loadNext([_htmCdn], 0, function() { _bootApp(cjOk); });
  });
});

/* ── Application ─────────────────────────────────────────────────────────── */
function _bootApp(cjOk) {
  try {
    if (typeof React    === 'undefined') { showErr('React CDN failed.');    return; }
    if (typeof ReactDOM === 'undefined') { showErr('ReactDOM CDN failed.'); return; }
    if (typeof htm      === 'undefined') { showErr('htm CDN failed.');      return; }

    var html       = htm.bind(React.createElement);
    var useState   = React.useState;
    var useMemo    = React.useMemo;
    var useEffect  = React.useEffect;
    var useRef     = React.useRef;

    var COLORS = [
      '#003153','#1863dc','#29b6f6','#0a4a7a','#4a9fd4',
      '#7dc0e8','#f0a500','#e05c2a','#6366f1','#10b981',
      '#ec4899','#f59e0b','#8b5cf6','#14b8a6','#ef4444',
    ];
    var PAGE = 50;

    /* ── CSV export ── */
    function exportCSV(rows, fname) {
      var hdrs = ['DocID','Date','Generic Name','Drug Class','Confidence','HCC Flag',
                  'Manual Review','ICD-10 Code 1','Description 1',
                  'ICD-10 Code 2','ICD-10 Code 3','ICD-10 Code 4','Data Source'];
      var lines = [hdrs.join(',')];
      rows.forEach(function(r) {
        var vals = [r.doc,r.dos,r.med,r.cls,r.conf,r.hcc,r.rev,r.icd1,r.desc1,r.icd2,r.icd3,r.icd4,r.src];
        lines.push(vals.map(function(v){ return '"'+(v||'').replace(/"/g,'""')+'"'; }).join(','));
      });
      var blob = new Blob([lines.join('\n')], {type:'text/csv'});
      var url  = URL.createObjectURL(blob);
      var a    = document.createElement('a');
      a.href   = url; a.download = fname || 'results.csv'; a.click();
      URL.revokeObjectURL(url);
    }

    /* ── KPI Card ── */
    function KPICard(p) {
      return html`
        <div class="card" style=${{
          borderTop:'4px solid '+p.color,
          borderLeft:'3px solid '+p.color,
          boxShadow:'0 4px 24px rgba(24,99,220,0.10), 0 1px 4px rgba(0,0,0,0.04)',
        }}>
          <div class="kpi-val" style=${{color:p.color}}>${p.value.toLocaleString()}</div>
          <div class="kpi-lbl">${p.icon} ${p.title}</div>
        </div>`;
    }

    /* ── Card wrapper ── */
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
      return html`<span class=${cls}>${p.v||'—'}</span>`;
    }

    /* ── Sort arrow ── */
    function Arrow(p) {
      if (p.col !== p.cur) return html`<span style=${{opacity:0.3}}> ↕</span>`;
      return html`<span> ${p.dir==='asc'?'↑':'↓'}</span>`;
    }

    /* ══════════════ Chart.js components ══════════════ */

    /* Horizontal bar — click to drill-down */
    function HBarChart(p) {
      var canvasRef = useRef(null);
      var chartRef  = useRef(null);
      var cfRef     = useRef(p.cf);    /* keep latest cf in ref so onClick closure is fresh */
      cfRef.current = p.cf;

      function getColors(activeVal) {
        return p.data.map(function(d, i) {
          var base = COLORS[p.ci != null ? p.ci : 1];
          return activeVal ? (d.name === activeVal ? base : 'rgba(0,0,0,0.1)') : base;
        });
      }

      useEffect(function() {
        if (!cjOk || !canvasRef.current) return;
        var ctx = canvasRef.current.getContext('2d');
        chartRef.current = new window.Chart(ctx, {
          type: 'bar',
          data: {
            labels: p.data.map(function(d){ return d.name; }),
            datasets: [{
              data:            p.data.map(function(d){ return d.value; }),
              backgroundColor: getColors(null),
              borderRadius:    3,
            }]
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: {
                label: function(ctx) { return ' ' + ctx.parsed.x + ' records'; },
                title: function(items) {
                  /* show ICD description in tooltip if available */
                  var idx = items[0].dataIndex;
                  var d   = p.data[idx];
                  return d.desc ? [d.name, d.desc] : [d.name];
                }
              }}
            },
            scales: {
              x: { grid: { color:'#e5edf5' }, ticks: { font:{size:10} } },
              y: { grid: { display:false },   ticks: { font:{size:11} } }
            },
            onHover: function(e, els) {
              e.native.target.style.cursor = els.length ? 'pointer' : 'default';
            },
            onClick: function(e, elements) {
              if (!elements.length) return;
              var name = p.data[elements[0].index].name;
              var cur  = cfRef.current;
              if (cur && cur.col === p.col && cur.value === name) { p.setCf(null); }
              else { p.setCf({ col: p.col, value: name,
                               label: (p.prefix || p.col) + ': ' + name }); }
              p.setPage(0);
            },
          }
        });
        return function() {
          if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; }
        };
      }, []);

      /* re-highlight bars when filter changes */
      useEffect(function() {
        if (!chartRef.current) return;
        var active = p.cf && p.cf.col === p.col ? p.cf.value : null;
        chartRef.current.data.datasets[0].backgroundColor = getColors(active);
        chartRef.current.update('none');
      }, [p.cf]);

      if (!cjOk) return html`<div class="no-chart">Chart unavailable — CDN offline</div>`;
      if (!p.data.length) return html`<div class="no-chart">No data</div>`;
      return html`
        <div style=${{height:(p.h||300)+'px', position:'relative'}}>
          <canvas ref=${canvasRef}></canvas>
        </div>`;
    }

    /* Donut chart — click to drill-down */
    function DonutChart(p) {
      var canvasRef = useRef(null);
      var chartRef  = useRef(null);
      var cfRef     = useRef(p.cf);
      cfRef.current = p.cf;

      useEffect(function() {
        if (!cjOk || !canvasRef.current) return;
        var ctx = canvasRef.current.getContext('2d');
        chartRef.current = new window.Chart(ctx, {
          type: 'doughnut',
          data: {
            labels: p.data.map(function(d){ return d.name; }),
            datasets: [{
              data:            p.data.map(function(d){ return d.value; }),
              backgroundColor: COLORS.slice(0, p.data.length),
              borderWidth: 2, borderColor: '#fff',
            }]
          },
          options: {
            cutout: '60%',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { position:'bottom', labels:{ font:{size:10}, padding:8 } },
              tooltip: {}
            },
            onHover: function(e, els) {
              e.native.target.style.cursor = els.length ? 'pointer' : 'default';
            },
            onClick: function(e, elements) {
              if (!elements.length) return;
              var name = p.data[elements[0].index].name;
              var cur  = cfRef.current;
              if (cur && cur.col === p.col && cur.value === name) { p.setCf(null); }
              else { p.setCf({ col: p.col, value: name,
                               label: (p.prefix || p.col) + ': ' + name }); }
              p.setPage(0);
            },
          }
        });
        return function() {
          if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; }
        };
      }, []);

      useEffect(function() {
        if (!chartRef.current) return;
        var active = p.cf && p.cf.col === p.col ? p.cf.value : null;
        chartRef.current.data.datasets[0].backgroundColor = p.data.map(function(d, i) {
          return active
            ? (d.name === active ? COLORS[i % COLORS.length] : 'rgba(0,0,0,0.1)')
            : COLORS[i % COLORS.length];
        });
        chartRef.current.update('none');
      }, [p.cf]);

      if (!cjOk) return html`<div class="no-chart">Chart unavailable — CDN offline</div>`;
      if (!p.data.length) return html`<div class="no-chart">No data</div>`;
      return html`
        <div style=${{height:(p.h||220)+'px', position:'relative'}}>
          <canvas ref=${canvasRef}></canvas>
        </div>`;
    }

    /* Line chart */
    function LineChart(p) {
      var canvasRef = useRef(null);
      useEffect(function() {
        if (!cjOk || !canvasRef.current) return;
        var ctx = canvasRef.current.getContext('2d');
        var ch = new window.Chart(ctx, {
          type: 'line',
          data: {
            labels: p.data.map(function(d){ return d.date; }),
            datasets: [{
              data:            p.data.map(function(d){ return d.count; }),
              borderColor:     '#1863dc',
              backgroundColor: 'rgba(24,99,220,0.08)',
              fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2,
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid:{ display:false }, ticks:{ font:{size:10}, maxRotation:45 } },
              y: { grid:{ color:'#e5edf5' }, ticks:{ font:{size:10} } }
            }
          }
        });
        return function() { ch.destroy(); };
      }, []);
      if (!cjOk || !p.data.length) return null;
      return html`
        <div style=${{height:(p.h||180)+'px', position:'relative'}}>
          <canvas ref=${canvasRef}></canvas>
        </div>`;
    }

    /* ══════════════ Main Dashboard ══════════════ */
    function Dashboard(p) {
      var d         = p.data;
      var kpi       = d.kpi        || {};
      var confidence= d.confidence || [];
      var topMeds   = d.top_meds   || [];
      var review    = d.review     || [];
      var hccFlags  = d.hcc_flags  || [];
      var topHcc    = d.top_hcc    || [];
      var topIcd    = d.top_icd    || [];
      var drugClass = d.drug_class || [];
      var dateTrend = d.date_trend || [];
      var table     = d.table      || [];

      /* filter state */
      var _s  = useState('');    var search    = _s[0];  var setSearch    = _s[1];
      var _fc = useState('All'); var fConf     = _fc[0]; var setFConf     = _fc[1];
      var _fr = useState('All'); var fRev      = _fr[0]; var setFRev      = _fr[1];
      var _fh = useState('All'); var fHcc      = _fh[0]; var setFHcc      = _fh[1];
      var _sc = useState(null);  var sortCol   = _sc[0]; var setSortCol   = _sc[1];
      var _sd = useState('asc'); var sortDir   = _sd[0]; var setSortDir   = _sd[1];
      var _pg = useState(0);     var page      = _pg[0]; var setPage      = _pg[1];
      var _cf = useState(null);  var cf        = _cf[0]; var setCf        = _cf[1];

      var hccOpts = useMemo(function() {
        var v = {}; table.forEach(function(r){ if(r.hcc) v[r.hcc]=1; });
        return Object.keys(v).sort();
      }, [table]);

      function handleSort(col) {
        if (sortCol===col) { setSortDir(function(d){ return d==='asc'?'desc':'asc'; }); }
        else { setSortCol(col); setSortDir('asc'); }
        setPage(0);
      }

      function clearAll() {
        setSearch(''); setFConf('All'); setFRev('All'); setFHcc('All'); setCf(null); setPage(0);
      }

      var filtered = useMemo(function() {
        var rows = table;
        var q = search.toLowerCase();
        if (q) rows = rows.filter(function(r) {
          return (r.med||'').toLowerCase().includes(q)  ||
                 (r.icd1||'').toLowerCase().includes(q) ||
                 (r.desc1||'').toLowerCase().includes(q)||
                 (r.doc||'').toLowerCase().includes(q)  ||
                 (r.cls||'').toLowerCase().includes(q);
        });
        if (fConf !== 'All') rows = rows.filter(function(r){ return r.conf === fConf; });
        if (fRev  !== 'All') rows = rows.filter(function(r){ return r.rev  === fRev;  });
        if (fHcc  !== 'All') rows = rows.filter(function(r){ return r.hcc  === fHcc;  });
        if (cf) {
          var col = cf.col, val = (cf.value||'').toLowerCase();
          if (col === 'icd_any') {
            rows = rows.filter(function(r) {
              return (r.icd1||'').toLowerCase()===val || (r.icd2||'').toLowerCase()===val ||
                     (r.icd3||'').toLowerCase()===val || (r.icd4||'').toLowerCase()===val;
            });
          } else if (col === 'hcc_cat') {
            /* HCC category spans 4 slots — match any */
            rows = rows.filter(function(r) {
              return (r.hcc1||'').toLowerCase()===val || (r.hcc2||'').toLowerCase()===val ||
                     (r.hcc3||'').toLowerCase()===val || (r.hcc4||'').toLowerCase()===val;
            });
          } else {
            rows = rows.filter(function(r){ return (r[col]||'').toLowerCase()===val; });
          }
        }
        if (sortCol) {
          var dir = sortDir;
          rows = rows.slice().sort(function(a,b){
            var c = String(a[sortCol]||'').localeCompare(String(b[sortCol]||''));
            return dir==='asc' ? c : -c;
          });
        }
        return rows;
      }, [table, search, fConf, fRev, fHcc, cf, sortCol, sortDir]);

      var totalPages = Math.max(1, Math.ceil(filtered.length / PAGE));
      var pageRows   = filtered.slice(page * PAGE, (page+1) * PAGE);

      /* shared chart props */
      var cp = { cf: cf, setCf: setCf, setPage: setPage };

      return html`<div>

        <div class="header">
          <h1>📊 Medication Analytics Dashboard</h1>
          <p>Click any chart bar or slice to drill-down filter the table · Chart.js ${cjOk?'✓':'— CDN offline, table still works'}</p>
        </div>

        <div class="body space-y">

          <!-- KPI row -->
          <div class="grid4">
            <${KPICard} title="Total Records"          value=${kpi.total||0}         color="#003153" icon="📋" />
            <${KPICard} title="Unique Members"         value=${kpi.unique_members||0} color="#1863dc" icon="👥" />
            <${KPICard} title="Manual Review Required" value=${kpi.manual_review||0}  color="#f0a500" icon="⚠️" />
            <${KPICard} title="High Value HCC Flagged" value=${kpi.high_hcc||0}       color="#e05c2a" icon="🏷️" />
          </div>

          <!-- Row 1: Confidence | Manual Review | HCC Flags -->
          <div class="grid3">
            <${Card} title="Confidence Level — click to filter">
              <${DonutChart} data=${confidence} col="conf" prefix="Confidence" h=${200} ...${cp} />
            <//>
            <${Card} title="Manual Review Flag — click to filter">
              <${DonutChart} data=${review} col="rev" prefix="Review" h=${200} ...${cp} />
            <//>
            <${Card} title="High Value HCC Flags — click to filter">
              <${HBarChart} data=${hccFlags} col="hcc" prefix="HCC Flag" ci=${1} h=${200} ...${cp} />
            <//>
          </div>

          <!-- Row 2: Top 20 Meds | Top 10 HCC -->
          <div class="grid2">
            <${Card} title="Top 20 Medications — click to filter">
              <${HBarChart} data=${topMeds} col="med" prefix="Medication" ci=${0} h=${420} ...${cp} />
            <//>
            <${Card} title="Top 10 HCC Categories">
              <${HBarChart} data=${topHcc} col="hcc_cat" prefix="HCC" ci=${2} h=${420} ...${cp} />
            <//>
          </div>

          <!-- Row 3: Top ICD | Drug Class -->
          <div class="grid2">
            <${Card} title="Top 15 ICD-10-CM Codes — click to filter">
              <${HBarChart} data=${topIcd} col="icd_any" prefix="ICD-10" ci=${4} h=${380} ...${cp} />
            <//>
            <${Card} title=${drugClass.length>0 ? 'Drug Class — click to filter' : 'Drug Class'}>
              ${drugClass.length > 0
                ? html`<${DonutChart} data=${drugClass} col="cls" prefix="Drug Class" h=${380} ...${cp} />`
                : html`<div class="no-chart">No drug class data in results</div>`}
            <//>
          </div>

          <!-- Date trend -->
          ${dateTrend.length > 0 && html`
            <${Card} title="Records by Date of Service">
              <${LineChart} data=${dateTrend} h=${180} />
            <//>
          `}

          <!-- Data table -->
          <${Card} title="Detailed Records — Filterable · Sortable · Exportable">

            ${cf && html`
              <div class="chart-filter-bar">
                <div>
                  <span class="chart-filter-label">🔍 Chart filter: </span>
                  <span class="badge badge-med" style=${{marginLeft:'6px'}}>${cf.label}</span>
                  <span class="chart-filter-hint" style=${{marginLeft:'10px'}}>
                    click same element to clear
                  </span>
                </div>
                <button class="btn" style=${{padding:'3px 12px',fontSize:'.75rem'}}
                  onClick=${function(){ setCf(null); setPage(0); }}>✕ Clear</button>
              </div>
            `}

            <div class="filter-bar">
              <input type="text"
                placeholder="🔍 Search name, ICD, description, DocID, drug class…"
                value=${search}
                onInput=${function(e){ setSearch(e.target.value); setPage(0); }} />
              <select value=${fConf}
                onChange=${function(e){ setFConf(e.target.value); setPage(0); }}>
                <option value="All">All Confidence</option>
                <option>High</option><option>Medium</option>
                <option>Low</option><option>Unknown</option>
              </select>
              <select value=${fRev}
                onChange=${function(e){ setFRev(e.target.value); setPage(0); }}>
                <option value="All">All Review</option>
                <option>YES</option><option>No</option>
              </select>
              <select value=${fHcc}
                onChange=${function(e){ setFHcc(e.target.value); setPage(0); }}>
                <option value="All">All HCC Flags</option>
                ${hccOpts.map(function(v){
                  return html`<option key=${v} value=${v}>${v}</option>`;
                })}
              </select>
              <button class="btn" onClick=${clearAll}>✕ Clear All</button>
            </div>

            <div class="tbl-header-row">
              <div class="row-count">
                Showing ${pageRows.length} of ${filtered.length} records (${table.length} total)
              </div>
              <button class="btn-export"
                onClick=${function(){ exportCSV(filtered, 'medication_results.csv'); }}>
                ⬇ Export CSV (${filtered.length} rows)
              </button>
            </div>

            <div class="tbl-wrap">
              <table>
                <thead><tr>
                  ${[['doc','DocID'],['dos','Date'],['med','Generic Name'],['cls','Drug Class'],
                     ['conf','Confidence'],['hcc','HCC Flag'],['rev','Review'],
                     ['icd1','ICD-10 Code'],['desc1','Description'],['src','Source']
                    ].map(function(c){
                    return html`
                      <th key=${c[0]} onClick=${function(){ handleSort(c[0]); }}>
                        ${c[1]}<${Arrow} col=${c[0]} cur=${sortCol} dir=${sortDir} />
                      </th>`;
                  })}
                </tr></thead>
                <tbody>
                  ${pageRows.map(function(row, i){
                    var other = [row.icd2, row.icd3, row.icd4]
                      .filter(function(x){ return x && x.trim(); }).join(', ');
                    return html`<tr key=${i}>
                      <td style=${{fontWeight:600}}>${row.doc}</td>
                      <td style=${{whiteSpace:'nowrap'}}>${row.dos}</td>
                      <td style=${{fontWeight:500}}>
                        ${row.med}
                        ${other && html`<div class="other-icds" title=${other}>+ ${other}</div>`}
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
                      <td>${row.src && html`<span class="src-tag">${row.src}</span>`}</td>
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
        data_json = data_json.replace("<", r"\u003c")

        return (
            "<!DOCTYPE html><html lang='en'><head>"
            "<meta charset='UTF-8'>"
            "<style>" + _CSS + "</style>"
            "<script>window.__DATA__ = " + data_json + ";</script>"
            "</head><body>"
            "<div id='root'><div id='loading'>⏳ Loading dashboard…</div></div>"
            "<script>" + _JS_TEMPLATE + "</script>"
            "</body></html>"
        )
    except Exception as e:
        return (
            "<!DOCTYPE html><html><body>"
            "<div class='err'><strong>Build error:</strong> " + str(e) + "</div>"
            "</body></html>"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def render_react_dashboard(df: pd.DataFrame) -> None:
    """Render the analytics dashboard from the processed results DataFrame."""
    data     = _compute_data(df)
    html_str = _build_html(data)
    components.html(html_str, height=3600, scrolling=True)
