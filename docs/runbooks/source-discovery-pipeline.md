# Source Discovery Pipeline Runbook

VidyaVerse source discovery is a trust pipeline, not an auto-ingest crawler. New sources move through discovery, qualification, extraction, probation, trust scoring, and admin review before production scraper promotion.

## Bootstrap

```bash
cd backend
python scripts/bootstrap_company_seeds.py
```

The script is idempotent and inserts up to 200 curated `CompanySeed` records. Existing domains are skipped.

## Required Configuration

- `DISCOVERY_ENABLED=true`
- `REDIS_URL` for queue-backed qualification/extraction batches
- `SERPAPI_KEY` for web-search discovery
- `CLAUDE_API_KEY` for LLM-assisted extraction
- `MAX_LLM_EXTRACTIONS_PER_HOUR` and `MONTHLY_LLM_BUDGET_USD` for cost control
- `ADMIN_WEBHOOK_URL` for promotion/quarantine/review notifications
- `QUALIFICATION_MIN_SCORE`, `TRUST_MIN_SCORE_AUTO_PROMOTE`, `TRUST_MIN_SCORE_REQUIRE_REVIEW`, `PROBATION_MIN_RUNS`, `PROBATION_MIN_PARSE_RATE`

## Scheduled Jobs

The API scheduler enqueues these Mongo-backed jobs when `DISCOVERY_ENABLED=true`:

- `company_seed_careers_finder`: daily 10 PM IST
- `source_discovery_run`: daily 11 PM IST
- `source_qualification_batch`: every 2 hours
- `source_extraction_batch`: every 4 hours
- `probation_scrape_run`: Monday/Wednesday/Friday 2 AM IST
- `source_health_monitor`: daily 6 AM IST
- `trust_score_recompute`: Sunday 4 AM IST

Manual enqueue is available from `/api/v1/admin/discovery/run` or the generic admin jobs endpoint.

## Admin API

- `GET /api/v1/admin/discovery/overview`
- `GET /api/v1/admin/discovery/sources?status=probation`
- `GET /api/v1/admin/discovery/sources/{id}/trust-analysis`
- `POST /api/v1/admin/discovery/sources/{id}/force-qualify`
- `POST /api/v1/admin/discovery/sources/{id}/trigger-extraction`
- `POST /api/v1/admin/discovery/sources/{id}/trigger-probation-run`
- `POST /api/v1/admin/sources/{id}/approve`
- `POST /api/v1/admin/discovery/bad-domains`
- `GET /api/v1/admin/discovery/llm-costs`

## User and Employer Inputs

- Candidates submit sources at `POST /api/v1/sources/submit`.
- Candidates view status at `GET /api/v1/sources/my-submissions`.
- Employers claim careers pages at `POST /api/v1/employer/claim-careers-page`, then verify with `POST /api/v1/employer/claim-careers-page/verify`.

Employer claims are not promoted until the generated verification token is present on the claimed careers page.

## Reliability Controls

- Bad domains short-circuit discovery and can be managed through the admin API.
- Robots.txt disallow rules add domains to the bad-domain list.
- LLM extraction is rate-limited hourly and tracked in `discovery_llm_calls`.
- Probation sources do not write into `opportunities` until promotion.
- Promoted dynamic sources are stored in `scraper_registrations`.
- Health monitoring quarantines sources with repeated failures, stale templates, or low health scores.

## Verification

```bash
python3 -m pytest -q backend/tests/test_source_discovery_pipeline.py backend/tests/test_scraper_ingestion.py
python3 -m pytest -q backend/tests
```

Runtime smoke checks:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/metrics | grep discovery_sources_in_pipeline
```

## Rollback

Set `DISCOVERY_ENABLED=false` to stop scheduling new discovery work. Existing promoted dynamic scrapers can be paused or quarantined through `scraper_registrations` and the admin review endpoints without deleting historical source records.
