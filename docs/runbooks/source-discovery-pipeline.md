# Source Discovery Pipeline Runbook

VidyaVerse source discovery is a trust pipeline, not an auto-ingest crawler. New sources move through discovery, qualification, extraction, probation, trust scoring, and admin review before production scraper promotion.

## Bootstrap

```bash
cd backend
python scripts/bootstrap_company_seeds.py
```

The script is idempotent and maintains the curated `CompanySeed` registry. Existing domains are updated with newer official careers URLs, priority tier, source category, target-role, and check-cadence metadata.

The highest-priority seed group is the official internship watchlist. It contains S-tier technology, consulting, finance, government/PSU, research, automotive/manufacturing, aerospace, energy, analytics, banking, FMCG, Indian product, IT services, and hidden-gem company careers pages. These seeds are not trusted blindly: the company-careers intelligence job still filters for internships, student programs, graduate/new-grad roles, and 0-1 year opportunities before writing anything to `opportunities`.

## Autonomous Discovery Intelligence

The discovery loop is designed to grow beyond the curated source list:

- Web-search discovery uses SerpAPI and the managed Firecrawl search fallback, plus data-informed queries built from recent profile interests, preferred roles, locations, opportunity tags, opportunity types, and active platform gaps.
- Third-party opportunity platforms are searched explicitly with early-career, off-campus, hackathon, research-internship, fresher, and 0-1 year query families.
- Each discovered URL receives an auditable `priority_score`, `priority_reasons`, and `priority_features` snapshot before it enters qualification.
- Priority scoring boosts official company seeds, tier-1/daily watchlist companies, student/early-career terms, India relevance, target AI/ML/software/data/product/finance/consulting domains, and platform-discovery signals.
- Priority scoring penalizes low-value advice/blog/training surfaces, pay-to-apply language, risky TLDs, and generic non-opportunity pages.
- Qualification and extraction fallback batches process highest-priority sources first. Redis-backed explicit queues are still honored for deterministic job handoff.

This is not blind auto-publishing. High-priority only means "spend scraper/LLM budget here first"; sources still need to pass qualification, extraction, probation, trust scoring, and promotion gates.

## Required Configuration

- `DISCOVERY_ENABLED=true`
- `REDIS_URL` for queue-backed qualification/extraction batches
- `SERPAPI_KEY` for the primary web-search discovery provider
- `FIRECRAWL_ENABLED=false` by default; set `FIRECRAWL_ENABLED=true`, `FIRECRAWL_API_KEY`, and `FIRECRAWL_API_URL` only for the managed JS rendering/search pilot
- `FIRECRAWL_MODE=fallback` for the recommended production routing policy. `preferred` sends render-eligible pages to Firecrawl first.
- `BROWSER_USE_ENABLED=false` by default; enable with `BROWSER_USE_API_KEY` only when Firecrawl is insufficient for blocked pages
- `CRAWLEE_ENABLED=false` by default; enable for local BeautifulSoup/Playwright fallback when managed providers fail
- `FIRECRAWL_MAX_CONCURRENT`, timeout/retry, cache-age, minimum-HTML, maximum-content, and circuit-breaker settings bound provider cost, memory, and failure impact
- `CLAUDE_API_KEY` for LLM-assisted extraction
- `MAX_LLM_EXTRACTIONS_PER_HOUR` and `MONTHLY_LLM_BUDGET_USD` for cost control
- `ADMIN_WEBHOOK_URL` for promotion/quarantine/review notifications
- `QUALIFICATION_MIN_SCORE`, `TRUST_MIN_SCORE_AUTO_PROMOTE`, `TRUST_MIN_SCORE_REQUIRE_REVIEW`, `PROBATION_MIN_RUNS`, `PROBATION_MIN_PARSE_RATE`

## Scheduled Jobs

The API scheduler enqueues these Mongo-backed jobs when `DISCOVERY_ENABLED=true`:

- `company_seed_careers_finder`: daily 10 PM IST
- `company_careers_ingest`: scheduled official careers-page ingestion for due high-priority company seeds
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
- Direct ATS/public JSON APIs stay on deterministic clients. Render-eligible HTML uses Firecrawl only when direct content is blocked, unhealthy, or too short in `fallback` mode.
- Firecrawl rejects credential-bearing URLs, localhost, internal host suffixes, and non-global IP targets before any provider request.
- Firecrawl requests have bounded concurrency, timeout/retry controls, cached-page reuse, a circuit breaker, and Prometheus request/latency metrics.
- LLM extraction is rate-limited hourly and tracked in `discovery_llm_calls`.
- Probation sources do not write into `opportunities` until promotion.
- Promoted dynamic sources are stored in `scraper_registrations`.
- Health monitoring quarantines sources with repeated failures, stale templates, or low health scores.

## Verification

```bash
python3 -m pytest -q backend/tests/test_firecrawl_integration.py backend/tests/test_scraper_fetch_providers.py backend/tests/test_source_discovery_pipeline.py backend/tests/test_scraper_ingestion.py
python3 -m pytest -q backend/tests
```

Runtime smoke checks:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/metrics | grep discovery_sources_in_pipeline
curl -fsS http://localhost:8000/metrics | grep firecrawl_requests_total
```

## Rollback

Set `FIRECRAWL_ENABLED=false` to return immediately to direct HTTP/ATS ingestion. Set `DISCOVERY_ENABLED=false` to stop scheduling new discovery work. Existing promoted dynamic scrapers can be paused or quarantined through `scraper_registrations` and the admin review endpoints without deleting historical source records.
