# UI Redesign Spec — HealthSmart MSO Medication Mapper
**Date:** 2026-05-10  
**Approach:** CSS-only refresh (A) + selective structural tightening on header + metric cards (B)  
**Files:** `app.py` (CSS block + HTML), `react_dashboard.py` (_CSS string)  
**Risk:** Low — zero changes to Python logic, parser, or output schema

---

## 1. Design Tokens

| Token | Old | New |
|---|---|---|
| Card shadow | `6px 6px 9px rgba(0,0,0,0.07)` | `0 2px 8px rgba(0,0,0,0.06)` |
| Card radius | `10px` | `12px` |
| Spacing base | inconsistent | 8px grid |
| Header height | ~120px | ~90px |
| Metric value size | `1.9rem` | `2.2rem` |
| Metric value weight | `800` | `900` |
| Footer text color | `#888` | `#94a3b8` |
| Border color | `#d0e8f5` | `#e2eef8` |

---

## 2. Header

- Reduce body padding: `1.3rem 2rem` → `0.9rem 2rem`
- Logo box: show "HS" initials fallback when image fails to load
- Top bar font: `0.69rem` → `0.65rem`, opacity `0.65` → `0.5`
- Tagline size: `0.74rem` (keep), opacity `0.55` → `0.5`
- Version pill: keep style, no change

---

## 3. Disclaimer Box

- Background: `#fff8e1/#fffde7` → `#fefce8` (softer amber)
- Padding: reduce top/bottom by 25% (`0.75rem` → `0.55rem`)
- Font size: `0.85rem` → `0.82rem`
- Shadow: `6px 6px 9px` → `0 2px 8px rgba(0,0,0,0.05)`

---

## 4. API Badges

- Remove `box-shadow` — border only
- Font: `0.77rem` → `0.75rem`
- Gap: `6px` → `5px`

---

## 5. Tabs

- Active tab: keep gradient, add `letter-spacing: 0.2px`
- Inactive text: `#003153` → `#4a6080`
- Tab bar bg: `#eaf4fb` → `#f0f7ff`

---

## 6. Metric Cards

- Top accent: `3px` → `4px`, `border-radius: 0` (flush)
- Value: `1.9rem` / 800 → `2.2rem` / 900
- Label spacing: `0.6px` → `0.8px`
- Card padding: `0.9rem 1rem` → `1rem 1.2rem`
- Hover lift: `translateY(-2px)` → `translateY(-3px)`
- Border: `#d0e8f5` → `#e2eef8`

---

## 7. Analytics Dashboard (react_dashboard.py)

- KPI cards: add `4px` left border in accent color
- Chart card shadow: `0 1px 4px rgba(0,0,0,.08)` → `0 2px 12px rgba(0,0,0,.06)`
- Card title color: `#556` → `#6b7a8d`
- Table `th` padding: `8px 10px` → `7px 12px`
- Alternating row bg: `#f0f7ff` → `#f8faff`
- Badge padding: `2px 10px` → `3px 12px`
- Filter input border: `#c5d8ef` → `#d0dff0`

---

## 8. Filters & Table

- Search + dropdowns: `border-radius: 9999px` → `10px`
- Filter row gap: add `gap: 0.6rem`
- Drill-down banner border-left: `4px` → `3px`, bg `#f0f7ff`
- Expander header bg: `#eaf4fb` → `#f0f6ff`

---

## 9. Export & Footer

- Download button border: `2px` → `1.5px`
- Footer color: `#888` → `#94a3b8`
- Footer border-top: `#e0e8f0` → `#e8eef6`
- Footer padding-bottom: add `1.5rem`

---

## Out of Scope

- No changes to `parser.py`, API clients, `hcc_lookup.py`
- No changes to 35-column output schema
- No changes to Streamlit framework or `requirements.txt`
- Chart interactivity (Chart.js drill-down) unchanged
