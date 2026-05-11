# Medication Mapper — Design System Rules (Codex CLI)

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

Tokens live **inline in `app.py`** inside `st.markdown("<style>...</style>", unsafe_allow_html=True)`. No external CSS file.

### Color Tokens

```
#003153   deep navy    (headers, primary text)
#0a4a7a   mid navy     (gradient midpoint)
#1863dc   bright blue  (primary interactive, buttons, active tabs)
#29b6f6   sky blue     (accents, section border, version pill)
#eaf4fb   pale blue    (light backgrounds, tab bar)
#d0e8f5   blue border  (card borders)
#b8ddf5   light border (input borders)
#212121   dark text
#556677   caption text
#f0a500   amber        (disclaimer, warning)
#e05c2a   orange       (HCC flag)
#ffffff   white
#f8fafc   page bg      (React dashboard)
```

IMPORTANT: Never hardcode hex colors. Match from the list above.

### Typography

- Font: `'Inter', 'Segoe UI', sans-serif`
- Body: 14px / #212121
- Labels: 0.85rem / #003153 / weight 600
- Captions: 0.80rem / #556677

### Radius & Shadow

- Pills: `border-radius: 9999px`
- Cards: `border-radius: 10px`
- Shadow: `box-shadow: 6px 6px 9px rgba(0,0,0,0.07)`
- Blue glow: `box-shadow: 6px 6px 9px rgba(24,99,220,0.2)`

### Gradients

```
Header:  linear-gradient(135deg, #003153 0%, #0a4a7a 45%, #1863dc 80%, #29b6f6 100%)
Button:  linear-gradient(135deg, #003153, #1863dc)
Hover:   linear-gradient(135deg, #1863dc, #29b6f6)
```

## CSS Architecture

All styles injected via `st.markdown("<style>...</style>", unsafe_allow_html=True)` at top of `app.py`.

IMPORTANT: Streamlit renders inside an iframe — external `.css` files do not apply. Always inject via `unsafe_allow_html=True`.

## React Dashboard (react_dashboard.py)

Stack: React 18 + htm + Chart.js 4 (CDN only, no npm, no transpilation).

- CSS: in `_CSS` string constant in `react_dashboard.py`
- Chart types: `HBarChart`, `DonutChart`, `LineChart`
- All charts support drill-down via `cf / setCf / setPage` props
- Data bridge: Python → `window.__DATA__` JSON in HTML template

IMPORTANT: Do NOT replace Chart.js with Recharts — Recharts UMD fails silently in Streamlit iframes.

## Streamlit Patterns

- Layout: `wide`, sidebar `collapsed`, max-width 2048px
- Caching: `@st.cache_data(ttl=60)` for API checks, `@functools.lru_cache` in API clients
- Session state keys: `results_df`, `results_mode`, `run_datetime`, `run_file_name`, `run_row_count`, `drill_filter`

## Figma MCP Integration Rules

### Required flow

1. `get_design_context` → structured node representation
2. `get_screenshot` → visual reference
3. Translate React + Tailwind output to Streamlit inline HTML/CSS using tokens above
4. For analytics components → convert to Chart.js / htm in `react_dashboard.py`
5. Validate against Figma screenshot

### Color mapping

- `bg-blue-900` / `blue-900` → `#003153`
- `bg-blue-600` / `blue-600` → `#1863dc`
- `bg-sky-400`  / `sky-400`  → `#29b6f6`
- `rounded-full` → `border-radius: 9999px`
- `shadow-md`    → `box-shadow: 6px 6px 9px rgba(0,0,0,0.07)`

### Asset handling

- IMPORTANT: Use localhost Figma MCP image URLs directly — do not substitute placeholders
- IMPORTANT: Do not install icon packages — use emoji or inline SVG
- Store downloaded static assets at project root

## Output Schema

35-column DataFrame from `parser.py`. Key columns: `MedicationsID`, `DocID`, `DateOfService`, `Normalized Generic Name`, `Possible ICD-10-CM Code 1-4`, `ICD-10 Description 1-4`, `HCC Category (ICD 1-4)`, `High Value HCC Flag`, `Confidence Level`, `Manual Review Flag`, `Data Source`.

IMPORTANT: Do not rename output columns without updating `app.py` AND `react_dashboard.py`.

## Deployment

```bash
# Local
streamlit run app.py

# Deploy (auto on push)
git add . && git commit -m "msg" && git pull origin main --rebase && git push
```

Dependencies: `streamlit>=1.35.0`, `pandas>=2.0.0`, `openpyxl>=3.1.0`, `requests>=2.28.0`, `plotly>=5.17.0`
