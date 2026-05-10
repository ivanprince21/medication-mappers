"""
version.py — Single source of truth for app version info.
Update VERSION and RELEASE_DATE whenever a new feature is deployed.
"""

VERSION      = "1.4.0"
RELEASE_DATE = "May 10, 2026"

CHANGELOG = """
**v1.4.0** (May 10, 2026)
- Fixed analytics dashboard: replaced Recharts with Chart.js (canvas-based)
  — root cause: Recharts CDN silently returned HTTP 200 HTML pages in Streamlit
  iframes, so typeof Recharts was never defined; Chart.js CDN is rock-solid
- Fixed HCC chart drill-down: clicking Top 10 HCC Categories now correctly
  filters the table (was matching against a missing hcc_cat field; now checks
  all 4 HCC category slots per row)
- Fixed NDC lookup: openFDA now tried first, RxNorm NDC fallback second
- Fixed NDC format: 11-digit codes converted to dashed 5-4-2 format for openFDA
  (e.g. 67877044690 → 67877-0446-90); 10-digit tries leading-zero and
  trailing-zero variants
- Added RxNorm NDC→RXCUI lookup via ndcstatus.json — covers generic manufacturers
  not registered in openFDA (Ascend Labs, Amneal, Marlex, etc.)
- Data Source strings capped at 24 chars; full error details in Ambiguity Notes

**v1.3.0** (May 9, 2026)
- Desktop GUI app (`desktop_app.py`) — run without a browser
- Drug dictionary expanded: 100+ medications with validated ICD-10 codes
- ICD-10 local cache (130 HIPAA-valid 2026 codes) — instant offline resolution
- ICD-10 MCP server wired in as offline-first fallback

**v1.2.0**
- NLM ICD-10-CM live lookup wired into parser (Step 3 enrichment)
- API status bar added (RxNorm, openFDA NDC, ICD-10 NLM)
- LRU caching + exponential backoff on all API clients

**v1.1.0**
- CMS-HCC Model v28 crosswalk enrichment (offline, local)
- High Value HCC callout section in results
- Dual lookup (RXCUI + name match) in parser

**v1.0.0**
- Initial release: structured CSV/Excel upload + free-text tab
- RxNorm API (NLM) and openFDA NDC API integration
- Local medication dictionary with 27 hand-curated drugs
"""
