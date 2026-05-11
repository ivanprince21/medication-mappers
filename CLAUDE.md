# Medication Mapper — Design System Rules (Claude Code)

## Project Overview

Streamlit Python app (+ embedded React 18 analytics dashboard) for medication-to-ICD-10-CM mapping and CMS-HCC v28 enrichment. Deployed on Streamlit Community Cloud. No build step, no transpilation.

## File Architecture

| File | Role |
|---|---|
| `app.py` | Main Streamlit UI — all CSS tokens, page config, tabs, results, export |
| `react_dashboard.py` | React 18 + htm + Chart.js analytics iframe via `st.components.v1.html()` |
| `parser.py` | Core routing + 35-column output |
| `rxnorm_client.py` | NLM RxNorm API (LRU cached) |
| `ndc_client.py` | openFDA NDC API (LRU cached, retry on 429) |
| `icd10_client.py` | NLM ICD-10 API |
| `hcc_lookup.py` | Local HCC crosswalk |
| `medication_dictionary.json` | Hand-curated + MEDI-C drugs |
| `hcc_crosswalk.json` | CMS-HCC v28 ICD-10 → HCC mapping |

IMPORTANT: Read `parser.py` before modifying output columns — the 35-column schema is consumed by both `app.py` and `react_dashboard.py`.

## Design Token System

Tokens live **inline in `app.py`** inside `st.markdown("<style>...</style>", unsafe_allow_html=True)`. There is no external CSS file or token config.

### Color Tokens

```
--navy-deep:   #003153   (headers, primary text, dark bg)
--navy-mid:    #0a4a7a   (gradient midpoint)
--blue:        #1863dc   (primary interactive, active tabs, buttons)
--blue-light:  #29b6f6   (accents, version pill, section border)
--blue-pale:   #eaf4fb   (light backgrounds, tab bar)
--blue-border: #d0e8f5   (card borders)
--blue-border2:#b8ddf5   (input borders)
--text-dark:   #212121   (all body text)
--text-mid:    #556677   (captions, secondary)
--amber:       #f0a500   (disclaimer border, warning)
--orange:      #e05c2a   (HCC flag color)
--white:       #ffffff
--bg-page:     #f8fafc   (React dashboard body)
```

IMPORTANT: Never hardcode hex colors in new UI elements. Match values from the list above.

### Typography

- Font: `'Inter', 'Segoe UI', sans-serif` (loaded via Google Fonts in `app.py` CSS)
- Body: 14px / #212121
- Labels: 0.85rem / #003153 / weight 600
- Captions: 0.80rem / #556677
- Section headers: 0.94rem / #003153 / weight 700

### Spacing & Radius

- Border radius — pills: `9999px`, cards: `10px`–`12px`, small elements: `6px`–`8px`
- Shadow: `box-shadow: 6px 6px 9px rgba(0,0,0,0.07)` (cards), `6px 6px 9px rgba(24,99,220,0.2)` (blue glow)
- Padding — cards: `0.9rem 1rem`, banners: `0.85rem 1.5rem`, header body: `1.3rem 2rem`

### Gradients

```
Header:   linear-gradient(135deg, #003153 0%, #0a4a7a 45%, #1863dc 80%, #29b6f6 100%)
Buttons:  linear-gradient(135deg, #003153, #1863dc)
Hover:    linear-gradient(135deg, #1863dc, #29b6f6)
Banner:   linear-gradient(135deg, #003153 0%, #0a4a7a 50%, #1863dc 100%)
```

## CSS Architecture

All styles live in a single `<style>` block injected at the top of `app.py`. To add new styles:

1. Append to the existing `st.markdown("""<style>...</style>""", unsafe_allow_html=True)` block
2. Target Streamlit internals with their data-testid selectors when needed (e.g. `[data-testid="stAppViewContainer"]`)
3. Use class names that match the existing pattern: `.metric-card`, `.api-badge`, `.section-header`, etc.

IMPORTANT: Streamlit renders in an iframe context — CSS must be injected via `st.markdown(..., unsafe_allow_html=True)`. Never use an external `.css` file.

## Reusable UI Patterns

### Cards
```html
<div class="metric-card">
  <div class="metric-value">{value}</div>
  <div class="metric-label">{LABEL TEXT}</div>
</div>
```

### API Status Badges
```html
<span class="api-badge api-online">🟢 Label: Online</span>
<span class="api-badge api-offline">🔴 Label: Offline</span>
<span class="api-badge api-local">🔵 Label</span>
```

### Section Headers
```python
st.markdown('<div class="section-header">Section Title</div>', unsafe_allow_html=True)
```

### Disclaimer Box
```html
<div class="disclaimer-box">⚠️ <strong>Label:</strong> text</div>
```

### Run Report Banner
```html
<div class="run-report-banner">
  <div><div class="run-report-title">Title</div><div class="run-report-meta">meta</div></div>
  <div style="text-align:right">...</div>
</div>
```

### HCC Flag Pill
```html
<span class="hcc-flag">HCC Label</span>
```

## React Dashboard (react_dashboard.py)

Stack: **React 18 + htm + Chart.js 4** — all loaded via CDN at runtime, no transpilation.

### CSS in the dashboard
CSS lives in the `_CSS` string constant in `react_dashboard.py`. Same color tokens apply. Grid classes: `.grid2`, `.grid3`, `.grid4`. Card class: `.card` with `.card-title`.

### Adding a new chart
1. Add data aggregation in `_compute_data()` — return a list of `{name, value}` dicts
2. Use `HBarChart` (horizontal bar), `DonutChart` (donut), or `LineChart` (line) components — they accept drill-down via `cf`, `setCf`, `setPage` props
3. Wrap in `<${Card} title="...">` template
4. Pass shared chart props: `...${cp}` (which includes `cf, setCf, setPage`)

IMPORTANT: Do NOT switch from Chart.js to Recharts — Recharts UMD silently returns 200 HTML in Streamlit iframes.

### Data bridge
Python data passes to JavaScript via `window.__DATA__ = {...}` injected in the HTML template. Add new keys in `_compute_data()` and consume them in the `Dashboard` component.

## Streamlit Patterns

### Session state keys
```python
st.session_state["results_df"]    # pd.DataFrame — processed results
st.session_state["results_mode"]  # "structured" | "freetext"
st.session_state["run_datetime"]  # datetime.utcnow()
st.session_state["run_file_name"] # source filename
st.session_state["run_row_count"] # int
st.session_state["drill_filter"]  # {value, columns, label} or None
```

### Caching
- API availability checks: `@st.cache_data(ttl=60)`
- API clients: `@functools.lru_cache` in client modules

### Layout
- `st.set_page_config(layout="wide", initial_sidebar_state="collapsed")`
- Max width: 2048px via `.block-container` CSS override
- Two main tabs: `tab_struct` (structured CSV/Excel) and `tab_text` (free text)

## Figma MCP Integration Rules

### Required flow for any UI change from Figma

1. Run `get_design_context` with the node's fileKey and nodeId
2. Run `get_screenshot` for visual reference
3. Translate Figma output (React + Tailwind) → Streamlit inline HTML/CSS using the token system above
4. Map Tailwind colors to the project's color tokens
5. Validate against Figma screenshot before marking complete

### Translation rules

- Tailwind `bg-blue-900` → `#003153`, `bg-blue-600` → `#1863dc`, `bg-sky-400` → `#29b6f6`
- Tailwind `rounded-full` → `border-radius: 9999px`
- Tailwind `shadow-md` → `box-shadow: 6px 6px 9px rgba(0,0,0,0.07)`
- Figma components → Streamlit `st.markdown(html, unsafe_allow_html=True)` blocks
- React components from Figma → convert to Chart.js / htm patterns in `react_dashboard.py` if part of the analytics dashboard

### Asset handling

- IMPORTANT: If Figma MCP returns a localhost image/SVG URL, use it directly
- IMPORTANT: Do NOT install new icon packages — use emoji (existing pattern) or SVG inline
- Static assets (logos): reference by URL or store at project root

## Output Column Schema (parser.py)

35 output columns — do not rename without updating both `app.py` and `react_dashboard.py`:

Key columns: `MedicationsID`, `DocID`, `DateOfService`, `Normalized Generic Name`, `Brand Name Match`, `Dosage`, `Possible Indication 1-3`, `Why Member May Take This Drug`, `Possible ICD-10-CM Code 1-4`, `ICD-10 Description 1-4`, `HCC Category (ICD 1-4)`, `HCC Model Hierarchy (ICD 1-4)`, `HCC Description (ICD 1-4)`, `High Value HCC Flag`, `Confidence Level`, `Manual Review Flag`, `Ambiguity Notes`, `Data Source`

## Deployment

```bash
# Local
streamlit run app.py

# Push to Streamlit Cloud (auto-deploys)
git add . && git commit -m "msg" && git pull origin main --rebase && git push
```

No build step required. `requirements.txt` drives cloud deps: `streamlit>=1.35.0`, `pandas>=2.0.0`, `openpyxl>=3.1.0`, `requests>=2.28.0`, `plotly>=5.17.0`.
