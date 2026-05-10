"""
version.py — Single source of truth for app version info.
Update VERSION and RELEASE_DATE whenever a new feature is deployed.
"""

VERSION      = "1.3.0"
RELEASE_DATE = "May 9, 2026"

CHANGELOG = """
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
