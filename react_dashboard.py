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
            "conf": "Confidence Level",
            "hcc":  "High Value HCC Flag",
            "rev":  "Manual Review Flag",
            "icd":  "Possible ICD-10-CM Code 1",
            "desc": "ICD-10 Description 1",
        }
        subset = {}
        for k, col in col_map.items():
            if col in df.columns:
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
.row-count{font-size:.75rem;color:#667;margin-bottom:6px}
.pagination{display:flex;justify-content:space-between;align-items:center;
  margin-top:12px}
.page-info{font-size:.75rem;color:#667}
.space-y>*+*{margin-top:16px}
.hcc-yes{color:#c2410c;font-weight:600}
.hcc-no{color:#9ca3af}
"""

# ─────────────────────────────────────────────────────────────────────────────
# JavaScript — htm + React + Recharts (no Babel, no JSX transpilation)
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: this is a plain string — no Python f-string, so { } are literal JS
_JS_TEMPLATE = r"""
var _cdns = [
  'https://unpkg.com/react@18.2.0/umd/react.production.min.js',
  'https://unpkg.com/react-dom@18.2.0/umd/react-dom.production.min.js',
  'https://unpkg.com/recharts@2.9.0/umd/Recharts.js',
  'https://unpkg.com/htm@3.1.1/dist/htm.umd.js'
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

loadNext(_cdns, 0, function() {
  try {
    var html = htm.bind(React.createElement);
    var useState = React.useState;
    var useMemo  = React.useMemo;
    var RC = Recharts;

    var COLORS = ['#003153','#1863dc','#29b6f6','#0a4a7a','#4a9fd4','#7dc0e8','#f0a500','#e05c2a'];
    var PAGE = 50;

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
      if (p.col !== p.cur) return html`<span style="opacity:.3"> ↕</span>`;
      return html`<span> ${p.dir === 'asc' ? '↑' : '↓'}</span>`;
    }

    /* ══ Main Dashboard ══ */
    function Dashboard(p) {
      var d = p.data;
      var kpi       = d.kpi       || {};
      var confidence= d.confidence|| [];
      var topMeds   = d.top_meds  || [];
      var review    = d.review    || [];
      var hccFlags  = d.hcc_flags || [];
      var topHcc    = d.top_hcc   || [];
      var dateTrend = d.date_trend|| [];
      var table     = d.table     || [];

      var _s = useState('');   var search = _s[0];   var setSearch = _s[1];
      var _fc= useState('All');var filterConf=_fc[0]; var setFilterConf=_fc[1];
      var _fr= useState('All');var filterRev=_fr[0];  var setFilterRev=_fr[1];
      var _fh= useState('All');var filterHcc=_fh[0];  var setFilterHcc=_fh[1];
      var _sc= useState(null); var sortCol=_sc[0];    var setSortCol=_sc[1];
      var _sd= useState('asc');var sortDir=_sd[0];    var setSortDir=_sd[1];
      var _pg= useState(0);    var page=_pg[0];       var setPage=_pg[1];

      var hccOpts = useMemo(function() {
        var vals = {};
        table.forEach(function(r){ if(r.hcc) vals[r.hcc]=1; });
        return Object.keys(vals).sort();
      }, [table]);

      function handleSort(col) {
        if (sortCol === col) { setSortDir(function(d){ return d==='asc'?'desc':'asc'; }); }
        else { setSortCol(col); setSortDir('asc'); }
        setPage(0);
      }

      function clearFilters() {
        setSearch(''); setFilterConf('All'); setFilterRev('All');
        setFilterHcc('All'); setPage(0);
      }

      var filtered = useMemo(function() {
        var rows = table;
        var q = search.toLowerCase();
        if (q) rows = rows.filter(function(r){
          return (r.med||'').toLowerCase().includes(q) ||
                 (r.icd||'').toLowerCase().includes(q) ||
                 (r.desc||'').toLowerCase().includes(q)||
                 (r.doc||'').toLowerCase().includes(q);
        });
        if (filterConf !== 'All') rows = rows.filter(function(r){ return r.conf===filterConf; });
        if (filterRev  !== 'All') rows = rows.filter(function(r){ return r.rev===filterRev; });
        if (filterHcc  !== 'All') rows = rows.filter(function(r){ return r.hcc===filterHcc; });
        if (sortCol) {
          var dir = sortDir;
          rows = rows.slice().sort(function(a,b){
            var cmp = String(a[sortCol]||'').localeCompare(String(b[sortCol]||''));
            return dir==='asc'?cmp:-cmp;
          });
        }
        return rows;
      }, [table, search, filterConf, filterRev, filterHcc, sortCol, sortDir]);

      var totalPages = Math.max(1, Math.ceil(filtered.length / PAGE));
      var pageRows   = filtered.slice(page * PAGE, (page+1) * PAGE);

      var totalRev = review.reduce(function(s,r){ return s+r.value; }, 0) || 1;
      var pctLabel = function(entry) {
        return entry.name + ': ' + ((entry.value/totalRev)*100).toFixed(0) + '%';
      };

      return html`
        <div>

          <!-- Header -->
          <div class="header">
            <h1>📊 Medication Analytics Dashboard</h1>
            <p>Interactive post-processing insights</p>
          </div>

          <div class="body space-y">

            <!-- KPI Row -->
            <div class="grid4">
              <${KPICard} title="Total Records"          value=${kpi.total||0}          color="#003153" icon="📋" />
              <${KPICard} title="Unique Members"         value=${kpi.unique_members||0}  color="#1863dc" icon="👥" />
              <${KPICard} title="Manual Review Required" value=${kpi.manual_review||0}   color="#f0a500" icon="⚠️" />
              <${KPICard} title="High Value HCC Flagged" value=${kpi.high_hcc||0}        color="#e05c2a" icon="🏷️" />
            </div>

            <!-- Row 1: Confidence | Manual Review | HCC Flag -->
            <div class="grid3">

              <${Card} title="Confidence Level">
                <${RC.ResponsiveContainer} width="100%" height=${220}>
                  <${RC.PieChart}>
                    <${RC.Pie} data=${confidence} dataKey="value" nameKey="name"
                      innerRadius=${55} outerRadius=${85} paddingAngle=${3}>
                      ${confidence.map(function(e,i){
                        return html`<${RC.Cell} key=${e.name} fill=${COLORS[i%COLORS.length]} />`;
                      })}
                    <//>
                    <${RC.Tooltip} />
                    <${RC.Legend} iconSize=${10} wrapperStyle=${{fontSize:'11px'}} />
                  <//>
                <//>
              <//>

              <${Card} title="Manual Review Flag">
                <${RC.ResponsiveContainer} width="100%" height=${220}>
                  <${RC.PieChart}>
                    <${RC.Pie} data=${review} dataKey="value" nameKey="name"
                      outerRadius=${85} label=${pctLabel} paddingAngle=${3}>
                      ${review.map(function(e,i){
                        return html`<${RC.Cell} key=${e.name} fill=${COLORS[i%COLORS.length]} />`;
                      })}
                    <//>
                    <${RC.Tooltip} />
                    <${RC.Legend} iconSize=${10} wrapperStyle=${{fontSize:'11px'}} />
                  <//>
                <//>
              <//>

              <${Card} title="High Value HCC Flags">
                <${RC.ResponsiveContainer} width="100%" height=${220}>
                  <${RC.BarChart} data=${hccFlags} margin=${{top:5,right:8,left:0,bottom:40}}>
                    <${RC.CartesianGrid} strokeDasharray="3 3" vertical=${false} />
                    <${RC.XAxis} dataKey="name" tick=${{fontSize:9,angle:-15,textAnchor:'end'}} interval=${0} />
                    <${RC.YAxis} tick=${{fontSize:10}} />
                    <${RC.Tooltip} />
                    <${RC.Bar} dataKey="value" fill="#1863dc" radius=${[3,3,0,0]} />
                  <//>
                <//>
              <//>

            </div>

            <!-- Row 2: Top 20 Meds | Top 10 HCC Categories -->
            <div class="grid2">

              <${Card} title="Top 20 Medications by Record Count">
                <${RC.ResponsiveContainer} width="100%" height=${420}>
                  <${RC.BarChart} layout="vertical" data=${topMeds}
                    margin=${{top:0,right:20,left:0,bottom:0}}>
                    <${RC.CartesianGrid} strokeDasharray="3 3" horizontal=${false} />
                    <${RC.XAxis} type="number" tick=${{fontSize:10}} />
                    <${RC.YAxis} type="category" dataKey="name" width=${155} tick=${{fontSize:11}} />
                    <${RC.Tooltip} />
                    <${RC.Bar} dataKey="value" fill="#003153" radius=${[0,3,3,0]} />
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

            </div>

            <!-- Date Trend -->
            <${Card} title="Record Count by Date of Service">
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

            <!-- Data Table -->
            <${Card} title="Detailed Records — Filterable & Sortable">

              <div class="filter-bar">
                <input type="text" placeholder="🔍 Search name, ICD, description, DocID..."
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
                <button class="btn" onClick=${clearFilters}>✕ Clear</button>
              </div>

              <div class="row-count">
                Showing ${pageRows.length} of ${filtered.length} records
                (${table.length} total)
              </div>

              <div class="tbl-wrap">
                <table>
                  <thead>
                    <tr>
                      ${[['id','Med ID'],['doc','DocID'],['dos','Date'],
                         ['med','Generic Name'],['conf','Confidence'],
                         ['hcc','HCC Flag'],['rev','Manual Review'],
                         ['icd','ICD-10 Code']].map(function(c){
                        return html`
                          <th key=${c[0]} onClick=${function(){ handleSort(c[0]); }}>
                            ${c[1]}<${Arrow} col=${c[0]} cur=${sortCol} dir=${sortDir} />
                          </th>`;
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    ${pageRows.map(function(row, i){
                      return html`
                        <tr key=${i}>
                          <td style="color:#9ca3af;font-size:.75rem">${row.id}</td>
                          <td style="font-weight:600">${row.doc}</td>
                          <td style="white-space:nowrap">${row.dos}</td>
                          <td style="font-weight:500">${row.med}</td>
                          <td><${ConfBadge} v=${row.conf} /></td>
                          <td class=${row.hcc&&row.hcc.startsWith('YES')?'hcc-yes':'hcc-no'}>
                            ${row.hcc}
                          </td>
                          <td>
                            ${row.rev==='YES'
                              ? html`<span class="badge badge-yes">YES</span>`
                              : row.rev==='No'
                              ? html`<span class="badge badge-no">No</span>`
                              : html`<span style="color:#9ca3af">${row.rev}</span>`}
                          </td>
                          <td style="font-family:monospace;font-size:.78rem">${row.icd}</td>
                        </tr>`;
                    })}
                    ${pageRows.length===0 && html`
                      <tr><td colSpan=${8}
                        style="text-align:center;padding:32px;color:#9ca3af">
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
});
"""


# ─────────────────────────────────────────────────────────────────────────────
# HTML builder
# ─────────────────────────────────────────────────────────────────────────────
def _build_html(data: dict) -> str:
    try:
        data_json = json.dumps(data, ensure_ascii=False, default=str)
        data_json = data_json.replace("</script>", r"<\/script>")

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
    html = _build_html(data)
    components.html(html, height=2950, scrolling=True)
