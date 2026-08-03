# Scraper Source Audit

Last full audit: **2026-06-25** via `scripts/audit_scraper_sources.py`.

## Summary (73 sources)

| Status | Count | Meaning |
|--------|------:|---------|
| ok | 29 | Parsed at least one opportunity |
| empty | 26 | Fetch succeeded but zero parsed rows |
| error | 1 | Fetch failed |
| disabled_probe | 17 | Already disabled in config |

Raw report: `benchmarks/scraper_source_audit.json`

## Actions taken after audit

1. **Hack2Skill parser updated** for `/hack/` and `/event/` URLs (legacy `vision.hack2skill.com` cards retained).
2. **API listings use direct fetch** (`render=False`) for `/api/` and `.rss` endpoints.
3. **23 generic portal sources disabled** via `SCRAPER_SOURCE_AUDIT_OVERRIDES` in `scraper.py` (empty/error/duplicate).
4. **Duplicate Naukri generic portal entry disabled**; dedicated `NaukriScraper` remains scheduled.

## Currently enabled generic portals (post-update)

Run to refresh:

```bash
cd backend
./venv/bin/python - <<'PY'
from app.services.scraper import merged_portal_listings
for row in merged_portal_listings():
    if row.get("enabled", True):
        print(row["source"])
PY
```

## Re-run audit

```bash
cd backend
./venv/bin/python scripts/audit_scraper_sources.py --max-items 6 --timeout-seconds 75
```
