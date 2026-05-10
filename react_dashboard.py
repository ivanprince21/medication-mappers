import json
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def _compute_data(df: pd.DataFrame) -> dict:
    data = {}

    # KPI
    try:
        total = len(df)
        unique_members = int(df["DocID"].nunique()) if "DocID" in df.columns else 0
        manual_review = int((df["Manual Review Flag"] == "YES").sum()) if "Manual Review Flag" in df.columns else 0
        high_hcc = int(df["High Value HCC Flag"].astype(str).str.startswith("YES").sum()) if "High Value HCC Flag" in df.columns else 0
        data["kpi"] = {
            "total": total,
            "unique_members": unique_members,
            "manual_review": manual_review,
            "high_hcc": high_hcc,
        }
    except Exception:
        data["kpi"] = {"total": 0, "unique_members": 0, "manual_review": 0, "high_hcc": 0}

    # Confidence Level
    try:
        vc = df["Confidence Level"].value_counts().reset_index()
        vc.columns = ["name", "value"]
        data["confidence"] = vc.sort_values("value", ascending=False).to_dict(orient="records")
    except Exception:
        data["confidence"] = []

    # Top 20 Medications
    try:
        med_col = "Normalized Generic Name"
        if med_col in df.columns:
            vc = df[med_col].value_counts()
            vc = vc[~vc.index.isin(["Unknown Medication", "Unknown", ""])]
            vc = vc.head(20).reset_index()
            vc.columns = ["name", "value"]
            data["top_meds"] = vc.sort_values("value", ascending=True).to_dict(orient="records")
        else:
            data["top_meds"] = []
    except Exception:
        data["top_meds"] = []

    # Manual Review Flag
    try:
        vc = df["Manual Review Flag"].value_counts().reset_index()
        vc.columns = ["name", "value"]
        data["review"] = vc.to_dict(orient="records")
    except Exception:
        data["review"] = []

    # HCC Flags
    try:
        vc = df["High Value HCC Flag"].value_counts().reset_index()
        vc.columns = ["name", "value"]
        data["hcc_flags"] = vc.sort_values("value", ascending=False).to_dict(orient="records")
    except Exception:
        data["hcc_flags"] = []

    # Top 10 HCC Categories
    try:
        hcc_cols = [c for c in ["HCC Category (ICD 1)", "HCC Category (ICD 2)", "HCC Category (ICD 3)", "HCC Category (ICD 4)"] if c in df.columns]
        if hcc_cols:
            combined = pd.concat([df[c].astype(str).str.strip() for c in hcc_cols], ignore_index=True)
            combined = combined[~combined.isin(["", "N/A", "Not mapped", "nan", "None", "NaT"])]
            vc = combined.value_counts().head(10).reset_index()
            vc.columns = ["name", "value"]
            data["top_hcc"] = vc.sort_values("value", ascending=True).to_dict(orient="records")
        else:
            data["top_hcc"] = []
    except Exception:
        data["top_hcc"] = []

    # Date Trend
    try:
        if "DateOfService" in df.columns:
            dates = pd.to_datetime(df["DateOfService"], errors="coerce")
            trend = dates.dropna().dt.strftime("%b %d")
            vc = trend.value_counts().reset_index()
            vc.columns = ["date", "count"]
            # Re-sort by actual date
            date_map = pd.Series(
                dates.dropna().values,
                index=dates.dropna().dt.strftime("%b %d").values
            )
            # Use original datetime for sorting
            temp = df.copy()
            temp["_parsed_date"] = pd.to_datetime(df["DateOfService"], errors="coerce")
            temp["_date_str"] = temp["_parsed_date"].dt.strftime("%b %d")
            trend_df = (
                temp.dropna(subset=["_parsed_date"])
                .groupby("_date_str")
                .agg(count=("_parsed_date", "count"), _sort=("_parsed_date", "min"))
                .reset_index()
                .rename(columns={"_date_str": "date"})
                .sort_values("_sort")
                [["date", "count"]]
            )
            data["date_trend"] = trend_df.to_dict(orient="records")
        else:
            data["date_trend"] = []
    except Exception:
        data["date_trend"] = []

    # Table — vectorized (no iterrows) for speed on large files
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
        _NULL = {"nan", "none", "nat", "none", ""}
        subset = {}
        for short_key, col_name in col_map.items():
            if col_name in df.columns:
                s = df[col_name].fillna("").astype(str).str.strip()
                s = s.where(~s.str.lower().isin(_NULL), "")
                subset[short_key] = s.tolist()
            else:
                subset[short_key] = [""] * len(df)
        # Transpose dict-of-lists → list-of-dicts
        n = len(df)
        data["table"] = [
            {k: subset[k][i] for k in subset}
            for i in range(n)
        ]
    except Exception:
        data["table"] = []

    return data


def _build_html(data: dict) -> str:
    try:
        data_json = json.dumps(data, ensure_ascii=False, default=str)
        # Prevent </script> inside the data block from closing the tag early
        data_json = data_json.replace("</script>", r"<\/script>")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>body{{margin:0;padding:0;background:#f8fafc;}}</style>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/recharts@2.12.7/umd/Recharts.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <script>window.__DATA__ = {data_json};</script>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const {{
      BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
      Tooltip, Legend, XAxis, YAxis, CartesianGrid, ResponsiveContainer
    }} = Recharts;

    const {{ useState, useMemo }} = React;

    const COLORS = ['#003153','#1863dc','#29b6f6','#0a4a7a','#4a9fd4','#7dc0e8','#f0a500','#e05c2a'];
    const PAGE_SIZE = 50;

    const KPICard = ({{title, value, color, icon}}) => (
      <div style={{{{borderTop: `4px solid ${{color}}`}}}} className="bg-white rounded-xl p-5 shadow-sm">
        <div className="text-3xl font-extrabold" style={{{{color}}}}>{{value.toLocaleString()}}</div>
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mt-1">{{icon}} {{title}}</div>
      </div>
    );

    const SectionCard = ({{title, children, extra}}) => (
      <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
        <div className="flex items-center justify-between mb-2">
          <div className="font-bold text-gray-700 text-sm uppercase tracking-wide">{{title}}</div>
          {{extra && <div className="text-xs text-gray-400">{{extra}}</div>}}
        </div>
        {{children}}
      </div>
    );

    const CONF_BADGE = {{
      High: 'bg-green-100 text-green-700',
      Medium: 'bg-blue-100 text-blue-700',
      Low: 'bg-yellow-100 text-yellow-700',
      Unknown: 'bg-gray-100 text-gray-500',
    }};

    function Dashboard({{data}}) {{
      const [search, setSearch] = useState('');
      const [filterConf, setFilterConf] = useState('All');
      const [filterReview, setFilterReview] = useState('All');
      const [filterHcc, setFilterHcc] = useState('All');
      const [sortCol, setSortCol] = useState(null);
      const [sortDir, setSortDir] = useState('asc');
      const [page, setPage] = useState(0);

      const hccOptions = useMemo(() => {{
        const vals = [...new Set((data.table || []).map(r => r.hcc).filter(Boolean))];
        return vals.sort();
      }}, [data.table]);

      const handleSort = (col) => {{
        if (sortCol === col) {{
          setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        }} else {{
          setSortCol(col);
          setSortDir('asc');
        }}
        setPage(0);
      }};

      const sortArrow = (col) => {{
        if (sortCol !== col) return <span className="opacity-30 ml-1">↕</span>;
        return <span className="ml-1">{{sortDir === 'asc' ? '↑' : '↓'}}</span>;
      }};

      const clearFilters = () => {{
        setSearch('');
        setFilterConf('All');
        setFilterReview('All');
        setFilterHcc('All');
        setPage(0);
      }};

      const filteredData = useMemo(() => {{
        let rows = data.table || [];
        const q = search.toLowerCase();
        if (q) {{
          rows = rows.filter(r =>
            (r.med || '').toLowerCase().includes(q) ||
            (r.icd || '').toLowerCase().includes(q) ||
            (r.desc || '').toLowerCase().includes(q) ||
            (r.doc || '').toLowerCase().includes(q)
          );
        }}
        if (filterConf !== 'All') rows = rows.filter(r => r.conf === filterConf);
        if (filterReview !== 'All') rows = rows.filter(r => r.rev === filterReview);
        if (filterHcc !== 'All') rows = rows.filter(r => r.hcc === filterHcc);
        if (sortCol) {{
          rows = [...rows].sort((a, b) => {{
            const cmp = String(a[sortCol] || '').localeCompare(String(b[sortCol] || ''));
            return sortDir === 'asc' ? cmp : -cmp;
          }});
        }}
        return rows;
      }}, [data.table, search, filterConf, filterReview, filterHcc, sortCol, sortDir]);

      const totalPages = Math.max(1, Math.ceil(filteredData.length / PAGE_SIZE));
      const pageData = filteredData.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

      const kpi = data.kpi || {{}};
      const confidence = data.confidence || [];
      const topMeds = data.top_meds || [];
      const review = data.review || [];
      const hccFlags = data.hcc_flags || [];
      const topHcc = data.top_hcc || [];
      const dateTrend = data.date_trend || [];

      const pctLabel = (entry) => `${{entry.name}}: ${{((entry.value / (review.reduce((s,r)=>s+r.value,0)||1))*100).toFixed(0)}}%`;

      return (
        <div className="min-h-screen bg-gray-50 font-sans pb-10">

          {{/* Header */}}
          <div style={{{{background: 'linear-gradient(135deg,#003153 0%,#1863dc 100%)'}}}} className="px-8 py-6 text-white mb-6">
            <div className="text-2xl font-extrabold tracking-tight">📊 Medication Analytics Dashboard</div>
            <div className="text-sm opacity-75 mt-1">Interactive post-processing insights</div>
          </div>

          <div className="px-6 space-y-6">

            {{/* KPI Row */}}
            <div className="grid grid-cols-4 gap-4">
              <KPICard title="Total Records" value={{kpi.total || 0}} color="#003153" icon="📋" />
              <KPICard title="Unique Members" value={{kpi.unique_members || 0}} color="#1863dc" icon="👥" />
              <KPICard title="Manual Review Required" value={{kpi.manual_review || 0}} color="#f0a500" icon="⚠️" />
              <KPICard title="High Value HCC Flagged" value={{kpi.high_hcc || 0}} color="#e05c2a" icon="🏷️" />
            </div>

            {{/* Charts Row 1 */}}
            <div className="grid grid-cols-3 gap-4">

              <SectionCard title="Confidence Level">
                <ResponsiveContainer width="100%" height={{230}}>
                  <PieChart>
                    <Pie data={{confidence}} dataKey="value" nameKey="name" innerRadius={{55}} outerRadius={{85}} paddingAngle={{3}}>
                      {{confidence.map((entry, i) => (
                        <Cell key={{entry.name}} fill={{COLORS[i % COLORS.length]}} />
                      ))}}
                    </Pie>
                    <Tooltip />
                    <Legend iconSize={{10}} wrapperStyle={{{{fontSize:'11px'}}}} />
                  </PieChart>
                </ResponsiveContainer>
              </SectionCard>

              <SectionCard title="Manual Review">
                <ResponsiveContainer width="100%" height={{230}}>
                  <PieChart>
                    <Pie data={{review}} dataKey="value" nameKey="name" outerRadius={{85}} label={{pctLabel}} paddingAngle={{3}}>
                      {{review.map((entry, i) => (
                        <Cell key={{entry.name}} fill={{COLORS[i % COLORS.length]}} />
                      ))}}
                    </Pie>
                    <Tooltip />
                    <Legend iconSize={{10}} wrapperStyle={{{{fontSize:'11px'}}}} />
                  </PieChart>
                </ResponsiveContainer>
              </SectionCard>

              <SectionCard title="High Value HCC Flag">
                <ResponsiveContainer width="100%" height={{230}}>
                  <BarChart data={{hccFlags}} margin={{{{top:5,right:10,left:0,bottom:40}}}}>
                    <CartesianGrid strokeDasharray="3 3" vertical={{false}} />
                    <XAxis dataKey="name" tick={{{{fontSize:9, angle:-15, textAnchor:'end'}}}} interval={{0}} />
                    <YAxis tick={{{{fontSize:10}}}} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#1863dc" radius={{[3,3,0,0]}} />
                  </BarChart>
                </ResponsiveContainer>
              </SectionCard>

            </div>

            {{/* Charts Row 2 */}}
            <div className="grid grid-cols-2 gap-4">

              <SectionCard title="Top 20 Medications">
                <ResponsiveContainer width="100%" height={{420}}>
                  <BarChart layout="vertical" data={{topMeds}} margin={{{{top:0,right:20,left:0,bottom:0}}}}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={{false}} />
                    <XAxis type="number" tick={{{{fontSize:10}}}} />
                    <YAxis type="category" dataKey="name" width={{150}} tick={{{{fontSize:11}}}} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#003153" radius={{[0,3,3,0]}} />
                  </BarChart>
                </ResponsiveContainer>
              </SectionCard>

              <SectionCard title="Top 10 HCC Categories">
                <ResponsiveContainer width="100%" height={{420}}>
                  <BarChart layout="vertical" data={{topHcc}} margin={{{{top:0,right:20,left:0,bottom:0}}}}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={{false}} />
                    <XAxis type="number" tick={{{{fontSize:10}}}} />
                    <YAxis type="category" dataKey="name" width={{160}} tick={{{{fontSize:11}}}} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#29b6f6" radius={{[0,3,3,0]}} />
                  </BarChart>
                </ResponsiveContainer>
              </SectionCard>

            </div>

            {{/* Date Trend */}}
            <SectionCard title="Date of Service Trend">
              <ResponsiveContainer width="100%" height={{220}}>
                <LineChart data={{dateTrend}} margin={{{{top:5,right:20,left:0,bottom:40}}}}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{{{fontSize:10, angle:-30, textAnchor:'end'}}}} interval={{"preserveStartEnd"}} />
                  <YAxis tick={{{{fontSize:10}}}} />
                  <Tooltip />
                  <Line type="monotone" dataKey="count" stroke="#1863dc" strokeWidth={{2}} dot={{false}} />
                </LineChart>
              </ResponsiveContainer>
            </SectionCard>

            {{/* Data Table */}}
            <SectionCard title="Detailed Records">

              {{/* Filter Bar */}}
              <div className="flex flex-wrap gap-2 mb-3 items-center">
                <input
                  type="text"
                  value={{search}}
                  onChange={{e => {{ setSearch(e.target.value); setPage(0); }}}}
                  placeholder="🔍 Search name, ICD, description..."
                  className="rounded-full border border-gray-300 px-3 py-1.5 text-sm flex-grow min-w-0 focus:outline-none focus:ring-2 focus:ring-blue-300"
                />
                <select
                  value={{filterConf}}
                  onChange={{e => {{ setFilterConf(e.target.value); setPage(0); }}}}
                  className="rounded-full border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-300"
                >
                  <option value="All">All Confidence</option>
                  <option value="High">High</option>
                  <option value="Medium">Medium</option>
                  <option value="Low">Low</option>
                  <option value="Unknown">Unknown</option>
                </select>
                <select
                  value={{filterReview}}
                  onChange={{e => {{ setFilterReview(e.target.value); setPage(0); }}}}
                  className="rounded-full border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-300"
                >
                  <option value="All">All Review</option>
                  <option value="YES">YES</option>
                  <option value="No">No</option>
                </select>
                <select
                  value={{filterHcc}}
                  onChange={{e => {{ setFilterHcc(e.target.value); setPage(0); }}}}
                  className="rounded-full border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-300"
                >
                  <option value="All">All HCC Flags</option>
                  {{hccOptions.map(v => <option key={{v}} value={{v}}>{{v}}</option>)}}
                </select>
                <button
                  onClick={{clearFilters}}
                  className="rounded-full bg-gray-100 border border-gray-300 px-4 py-1.5 text-sm hover:bg-gray-200 transition whitespace-nowrap"
                >
                  Clear Filters
                </button>
              </div>

              <div className="text-xs text-gray-500 mb-2">
                Showing {{pageData.length}} of {{filteredData.length}} records ({{(data.table || []).length}} total)
              </div>

              {{/* Table */}}
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr style={{{{background: 'linear-gradient(135deg,#003153 0%,#1863dc 100%)', color:'white'}}}}>
                      {{[
                        {{key:'id', label:'Med ID'}},
                        {{key:'doc', label:'DocID'}},
                        {{key:'dos', label:'Date of Service'}},
                        {{key:'med', label:'Generic Name'}},
                        {{key:'conf', label:'Confidence'}},
                        {{key:'hcc', label:'HCC Flag'}},
                        {{key:'rev', label:'Manual Review'}},
                        {{key:'icd', label:'ICD-10 Code'}},
                      ].map(col => (
                        <th
                          key={{col.key}}
                          onClick={{() => handleSort(col.key)}}
                          className="cursor-pointer select-none px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide whitespace-nowrap hover:bg-white hover:bg-opacity-10 transition"
                        >
                          {{col.label}}{{sortArrow(col.key)}}
                        </th>
                      ))}}
                    </tr>
                  </thead>
                  <tbody>
                    {{pageData.map((row, i) => (
                      <tr
                        key={{i}}
                        className={{`${{i % 2 === 0 ? 'bg-white' : 'bg-blue-50'}} hover:bg-blue-100 transition`}}
                      >
                        <td className="px-3 py-2 text-gray-500 text-xs">{{row.id}}</td>
                        <td className="px-3 py-2 font-medium text-gray-700">{{row.doc}}</td>
                        <td className="px-3 py-2 text-gray-600 whitespace-nowrap">{{row.dos}}</td>
                        <td className="px-3 py-2 font-medium text-gray-800">{{row.med}}</td>
                        <td className="px-3 py-2">
                          {{row.conf ? (
                            <span className={{`rounded-full px-2 py-0.5 text-xs font-semibold ${{CONF_BADGE[row.conf] || CONF_BADGE.Unknown}}`}}>
                              {{row.conf}}
                            </span>
                          ) : null}}
                        </td>
                        <td className={{`px-3 py-2 text-xs font-semibold ${{row.hcc && row.hcc.startsWith('YES') ? 'text-orange-600' : 'text-gray-400'}}`}}>
                          {{row.hcc}}
                        </td>
                        <td className="px-3 py-2">
                          {{row.rev === 'YES' ? (
                            <span className="rounded-full px-2 py-0.5 text-xs font-semibold bg-red-100 text-red-700">YES</span>
                          ) : row.rev === 'No' ? (
                            <span className="rounded-full px-2 py-0.5 text-xs font-semibold bg-green-100 text-green-700">No</span>
                          ) : (
                            <span className="text-gray-400 text-xs">{{row.rev}}</span>
                          )}}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-gray-700">{{row.icd}}</td>
                      </tr>
                    ))}}
                    {{pageData.length === 0 && (
                      <tr>
                        <td colSpan={{8}} className="text-center py-8 text-gray-400 text-sm">No records match your filters.</td>
                      </tr>
                    )}}
                  </tbody>
                </table>
              </div>

              {{/* Pagination */}}
              <div className="flex justify-between items-center mt-3">
                <button
                  onClick={{() => setPage(p => Math.max(0, p - 1))}}
                  disabled={{page === 0}}
                  className="rounded-full border border-gray-300 px-4 py-1 text-sm disabled:opacity-30 enabled:hover:bg-blue-50 transition"
                >
                  ← Prev
                </button>
                <span className="text-xs text-gray-500">
                  Page {{page + 1}} of {{totalPages}} &nbsp;·&nbsp; {{filteredData.length}} records
                </span>
                <button
                  onClick={{() => setPage(p => Math.min(totalPages - 1, p + 1))}}
                  disabled={{page >= totalPages - 1}}
                  className="rounded-full border border-gray-300 px-4 py-1 text-sm disabled:opacity-30 enabled:hover:bg-blue-50 transition"
                >
                  Next →
                </button>
              </div>

            </SectionCard>

          </div>
        </div>
      );
    }}

    ReactDOM.createRoot(document.getElementById('root')).render(
      <Dashboard data={{window.__DATA__}} />
    );
  </script>
</body>
</html>"""
        return html
    except Exception as e:
        return f"""<!DOCTYPE html><html><body>
<div style="color:red;font-family:monospace;padding:20px;">
  <strong>Dashboard render error:</strong><br>{str(e)}
</div>
</body></html>"""


def render_react_dashboard(df: pd.DataFrame) -> None:
    data = _compute_data(df)
    html = _build_html(data)
    components.html(html, height=2900, scrolling=True)
