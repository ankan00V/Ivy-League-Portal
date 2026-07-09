# VidyaVerse

> AI-powered opportunity intelligence platform that helps students discover, prioritize, and act on internships, research roles, scholarships, and hackathons.

**Last updated:** June 19, 2026
**Status:** Active build, production-readiness gates enabled

## 1) Executive Summary
VidyaVerse is a full-stack AI/ML system, not just a listings app.
It combines ingestion, semantic retrieval, learned ranking, explainable AI responses, experimentation, and operational guardrails in one product loop.

**Core thesis:** Better opportunity outcomes require a system that continuously learns from user behavior, not static keyword filters.

## 2) Problem and Motivation
Students search fragmented portals with inconsistent quality, duplicate postings, and weak relevance ordering. The result is high effort and low conversion.

VidyaVerse addresses this with:
- retrieval quality (semantic + vector-based)
- ranking quality (behavior-informed learned ranker)
- explainability (RAG answer panel with grounded context)
- measurement (online/offline experiment and parity gates)

## 3) What Makes This Stand Out
Compared with standard portal architectures, this system adds:
- **Closed learning loop:** impressions -> clicks/saves/applies -> retrain -> gated promotion
- **Evidence-driven ranking:** `baseline | semantic | ml | ab` modes with measurable lift
- **Self-growing source network:** discovered sources pass qualification, extraction, probation, trust scoring, and admin review before production promotion
- **Production security posture:** Redis-backed cookie sessions, CSRF double-submit, CSP/Trusted Types, abuse locks, audit logs
- **Operational maturity:** CI release gates, incident artifacts, scheduled scorecards, synthetic checks
- **Privileged governance:** hidden admin control plane with strict single-admin + TOTP

## 4) Architecture
```mermaid
flowchart LR
    A["External Sources"] --> A1["Source Discovery Trust Gate"]
    A1 --> B["Scraper Ingestion"]
    B --> C["Dedup + Canonicalization"]
    C --> D[("MongoDB")]

    U["User Query / Context"] --> E["Embeddings + NLP"]
    D --> F["Vector Retrieval"]
    E --> F
    F --> G["RAG Insights"]

    D --> H["Ranking Service"]
    I["Profile + Interaction History"] --> H
    H --> J["Personalized Feed"]

    J --> K["Interaction Logging"]
    K --> L["Experiment Analytics"]
    K --> M["MLOps Retrain + Drift"]
    M --> H
```

## 5) Technology Stack
| Layer | Technologies |
|---|---|
| Frontend | Next.js 16, TypeScript, Playwright |
| Backend | FastAPI, Pydantic, Beanie ODM |
| Data | Managed MongoDB, managed Redis, managed ClickHouse |
| AI/ML | sentence-transformers, vector retrieval, learned ranker |
| Storage | S3-compatible production artifact store |
| Observability/Ops | GitHub Actions, Prometheus metrics, Grafana/BI, Slack/PagerDuty hooks |
| Security | HttpOnly session cookies, Redis-backed sessions, CSRF double-submit, CSP, Trusted Types, auth abuse controls |

## 6) Implemented Scope
### Product
- Guest-accessible dashboard preview for unauthenticated users.
- Personalized dashboard behavior for signed-in users.
- Candidate + employer user journeys.
- Ask AI opportunity assistant.

### AI/ML
- Multi-source ingestion with semantic deduplication.
- Vector retrieval + NLP intent/NER support.
- Ranking modes: `baseline`, `semantic`, `ml`, `ab`.
- Learned ranker retraining, drift checks, and activation policy.
- Offline benchmark and online parity/champion-challenger gates.

### Platform
- MongoDB-first backend architecture + Redis support.
- Background jobs with retry, dead-letter behavior, bounded concurrency, queue caps, and handler timeouts.
- Source discovery pipeline with company seeds, user submissions, qualification queues, adaptive extraction, probation, dynamic scraper registration, and health quarantine.
- Official company careers intelligence with a curated S-tier internship watchlist across global tech, quant/trading, Indian product, IT services, government/PSU, research, consulting, analytics, banking, manufacturing, aerospace, energy, FMCG, and hidden-gem employers.
- The intelligent source-discovery loop continues expanding beyond the curated list through company seeds, careers-page crawling, web search, similar-source expansion, employer claims, and admin review.
- Autonomous discovery now generates data-informed web queries from profile interests and opportunity history, searches for third-party opportunity platforms, and stores auditable priority scores/reasons so qualification and extraction spend budget on the highest-value internship and 0-1 year sources first.
- Remote job ingestion is constrained to internships, entry-level, junior, fresher, new-grad, trainee, apprentice, no-experience, or explicit 0-1 year roles. Senior, lead, principal, staff, manager, director, architect, 2+ year, bootcamp, and paid-training posts are filtered out before persistence.
- Staging integrated E2E framework and release-blocking checks.

### Security and Governance
- Cookie-first auth with Redis-backed server-side session state in production.
- CSRF origin checks plus double-submit token validation for unsafe requests under cookie auth.
- Security headers with strict CSP + Trusted Types controls.
- Auth lockout/audit instrumentation.
- Hidden admin control plane with TOTP and admin action auditing.

## 7) Metrics and Impact
<!-- DATASET_SNAPSHOT:START -->

## Dataset Size (Verified Snapshot)
Snapshot date: **July 09, 2026**

- Opportunities: **330**
- Applications: **0**
- Opportunity interactions: **15,706**
- Experiments: **3**
- Experiment assignments: **300**
- Ranking model versions: **335**
- Drift reports: **336**
- Profiles: **319**
- Users: **323**

Source distribution for opportunities:
- `freshersworld`: 61
- `internshala`: 58
- `indeed_india`: 53
- `unstop`: 32
- `linkedin`: 19
- `ivy_rss`: 15
- `hackerearth`: 12
- `ycombinator_jobs`: 12
- `aicte_internship`: 10
- `makeintern`: 9
- `wayup`: 9
- `devfolio`: 8
- `devpost`: 8
- `foundit`: 8
- `promilo`: 7
- `hack2skill`: 5
- `codeforces`: 2
- `handshake`: 1
- `techgig`: 1

<!-- DATASET_SNAPSHOT:END -->

### Offline retrieval quality
- Precision@5: **0.0667 -> 0.2000** (**+200%**)
- Recall@5: **0.3333 -> 1.0000** (**+200%**)
- nDCG@5: **0.3333 -> 1.0000** (**+200%**)
- MRR@5: **0.3333 -> 1.0000** (**+200%**)

### Real pilot lift (14-day window)
- CTR lift (`ml` vs baseline): **+58.21%** (p < 0.001)
- Apply-rate lift (`ml` vs baseline): **+153.22%** (p < 0.01)
- Save-rate lift (`ml` vs baseline): **+138.78%** (p < 0.001)

### Model lifecycle snapshot
<!-- MODEL_VERSION_METADATA:START -->

Updated: **2026-04-18T07:04:42.628589**

Policy: `guarded` (auto_activate=False, min_auc_gain=0.0, min_positive_rate=0.005, max_weight_shift=0.35)
Schedule: retrain every `24h`, drift check every `6h`, drift-triggered retrain=`True`
Alerts: enabled=`True`, cooldown=`120m`

Active model: `69e1c43e` (ranking-weights-v2) rows=11530 auc_gain=0.020068 activation_reason=`auto_activate_disabled`

Recent model versions:

| id | created_at | active | rows | auc_default | auc_learned | auc_gain | positive_rate | activation_reason |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `69e32cf4` | 2026-04-18T07:04:20.592000 | no | 11530 | 0.547235 | 0.565407 | 0.018172 | 0.159237 | weight_shift_above_threshold:1.400000>0.350000 |
| `69e1c43e` | 2026-04-17T05:25:18.324000 | yes | 11530 | 0.547235 | 0.567303 | 0.020068 | 0.159237 | auto_activate_disabled |
| `69e1c37a` | 2026-04-17T05:22:02.094000 | no | 11530 | 0.530699 | 0.543927 | 0.013229 | 0.159237 | auto_activate_disabled |
| `69e1c362` | 2026-04-17T05:21:38.033000 | no | 11530 | 0.530699 | 0.543927 | 0.013229 | 0.159237 | auto_activate_disabled |
| `69e1c2d3` | 2026-04-17T05:19:15.238000 | no | 11530 | 0.530699 | 0.543927 | 0.013229 | 0.159237 | auto_activate_disabled |
| `69e12a18` | 2026-04-16T18:27:36.837000 | no | 11530 | 0.530699 | 0.543927 | 0.013229 | 0.159237 | auto_activate_disabled |
| `69e121b1` | 2026-04-16T17:51:45.261000 | no | 11530 | 0.530699 | 0.543927 | 0.013229 | 0.159237 | auto_activate_disabled |
| `69e1213f` | 2026-04-16T17:49:51.023000 | no | 11530 | 0.530699 | 0.543927 | 0.013229 | 0.159237 | auto_activate_disabled |
| `69e11e3d` | 2026-04-16T17:37:01.303000 | no | 11530 | 0.530699 | 0.543927 | 0.013229 | 0.159237 | auto_activate_disabled |
| `69e10cf1` | 2026-04-16T16:23:13.598000 | no | 4480 | 0.523782 | 0.513580 | -0.010202 | 0.143080 | n/a |
| `69e10c4a` | 2026-04-16T16:20:26.935000 | no | 4480 | 0.523782 | 0.513580 | n/a | 0.143080 | n/a |
| `69e10c0e` | 2026-04-16T16:19:26.647000 | no | 0 | 0.000000 | 0.000000 | n/a | 0.000000 | n/a |

Latest drift report: id=`69e32d07` alert=`False` psi=0.030294 max_z=0.069408 notified_at=n/a

<!-- MODEL_VERSION_METADATA:END -->

### Engineering quality signal
- Focused scraper/source contract suite: **36 passing tests** (latest run on June 18, 2026)
- Production infra readiness gate: managed MongoDB, Redis, ClickHouse, and S3-compatible artifact storage have been verified from the local runtime; the full strict gate still requires deployed frontend/backend domains and a production BI URL.
- Local developer harness smoke: backend, MongoDB, Redis, queue, embedding model, learned ranker, artifact store, warehouse freshness, public opportunities, API docs, and frontend routes passed on June 19, 2026; this is not production deployment proof.
- Backend full suite baseline: **200 passing tests** (latest recorded full run on June 3, 2026)
- Frontend lint: **passing**
- Frontend production build: **passing**
- Security and release gates: **active in CI**

## 8) Reliability and Security Posture
- Session architecture favors HttpOnly cookie trust boundaries.
- CSRF origin/referer enforcement plus double-submit token validation for unsafe methods.
- Strict CSP/Trusted Types controls integrated in security headers.
- Auth abuse lock policy with structured audit events.
- Production startup guardrails enforce secure host/CORS/CSP/cookie expectations.
- Privileged admin access segmented with dedicated auth path + TOTP + RBAC checks.

## 9) Current Production Readiness Boundary
- The codebase contains production gates, env contracts, CI workflows, security guardrails, managed-infra checks, and operational runbooks.
- Production runtime must use deployed services: managed MongoDB, managed Redis, managed ClickHouse, S3-compatible artifact storage, live frontend/backend domains, configured OAuth/Turnstile/SMTP, production BI, and real alert destinations.
- Local Docker, localhost ports, MinIO, and local `.env` values are only a developer verification harness. They are not the production architecture and are rejected by the strict production infrastructure readiness gate.
- Without the real production secrets and deployed service endpoints, production can be validated only up to contract/readiness checks, not proven live.

## 10) What Is In Progress
- Increase sustained real-user traffic volume for stronger statistical confidence.
- Complete full staging secret and ownership wiring across environments.
- Expand multi-role staging E2E matrix (success + failure + recovery paths).
- Promote strict production enforcement toggles once ops readiness is consistently stable.

## 11) Vision
Build VidyaVerse into a benchmark-grade Data Science + AI/ML + Full-Stack system where:
- ranking decisions are measurable and auditable,
- model promotion is policy-gated,
- product changes are experiment-driven,
- security and reliability remain first-class engineering constraints.

## 12) Production Deployment Contract
Production deployment is environment-first. Configure secrets in the hosting platform or secret manager, not in committed files.

Required templates:
- `backend/.env.production.example`
- `frontend/.env.production.example`

Required production checks:
```bash
make validate-env
make release-contracts
make infra-check
make warehouse-refresh
make ds-gates
```

`make infra-check` is strict by default. It fails when MongoDB, Redis, ClickHouse, artifact storage, or BI point at localhost, Docker service names, MinIO, or other local/dev infrastructure.

Required external services:
- MongoDB with TLS and production credentials.
- Redis or Upstash-compatible Redis for sessions, queues, rate limits, and online features.
- ClickHouse with TLS for analytics marts.
- S3-compatible artifact storage for model artifacts.
- Production domains for frontend and backend.
- Production BI URL for analytics inspection.
- SMTP, OAuth, Turnstile, and alerting secrets.

## 13) Developer Verification Harness
Use this only to reproduce checks before production deployment. It is not the production architecture.

```bash
make local-prod
python3 scripts/smoke_test_local.py \
  --backend-url http://127.0.0.1:8010 \
  --frontend-url http://127.0.0.1:3002 \
  --require-artifact-store \
  --require-warehouse-fresh
```

The local harness uses Docker dependencies and ignored `.env` placeholders only to prove code paths. Do not promote those values to production.

## 14) Key Configuration Areas
- Production endpoints: `MONGODB_URL`, `REDIS_URL`, `ANALYTICS_WAREHOUSE_CLICKHOUSE_*`, `MLOPS_MODEL_ARTIFACT_S3_*`, `MODEL_ARTIFACT_BUCKET`
- Auth/Security: `AUTH_SESSION_COOKIE_*`, `AUTH_COOKIE_ONLY_MODE`, `CSRF_*`, `SECURITY_CSP_*`
- Session store: `AUTH_SESSION_STORE_ENABLED`, `AUTH_SESSION_REQUIRE_SERVER_STATE`, `AUTH_SESSION_BIND_DEVICE`
- Job scaling: `JOBS_MAX_CONCURRENCY`, `JOBS_HANDLER_TIMEOUT_SECONDS`, `JOBS_MAX_PENDING_PER_TYPE`
- Admin bootstrap: `ADMIN_BOOTSTRAP_ENABLED`, `ADMIN_BOOTSTRAP_EMAIL`, `ADMIN_BOOTSTRAP_PASSWORD`, `ADMIN_TOTP_SECRET`
- MLOps alerts/incidents: `MLOPS_ALERT_SLACK_WEBHOOK_URL`, `MLOPS_ALERT_PAGERDUTY_ROUTING_KEY`, `MLOPS_INCIDENT_DEFAULT_OWNER`
- Parity gates: `MLOPS_PARITY_*`
- Source discovery: `DISCOVERY_ENABLED`, `SERPAPI_KEY`, `CLAUDE_API_KEY`, `MAX_LLM_EXTRACTIONS_PER_HOUR`, `MONTHLY_LLM_BUDGET_USD`, `QUALIFICATION_MIN_SCORE`, `TRUST_MIN_SCORE_AUTO_PROMOTE`, `PROBATION_*`, `SOURCE_FETCH_RATE_LIMIT`

## 15) High-Value Code Paths
- Backend core: `backend/app`
- Frontend core: `frontend/src`
- CI/CD workflows: `.github/workflows`
- Runbooks: `docs/runbooks`
- Hidden admin security architecture: `docs/runbooks/hidden-admin-security-architecture.md`
- Source discovery operations: `docs/runbooks/source-discovery-pipeline.md`
- Production data/ML operations: `docs/runbooks/data-platform-and-mlops.md`
- Source discovery: `backend/app/models/source_discovery.py`, `backend/app/services/source_discovery.py`, `backend/scripts/bootstrap_company_seeds.py`
- Data bootstrap: `backend/scripts/bootstrap_opportunities.py`, `backend/scripts/seed_test_data.py`, `backend/scripts/validate_data_health.py`, `backend/scripts/export_dataset_snapshot.py`

## 16) Production Bootstrap Commands
```bash
make bootstrap-opportunities
make validate-data-health
make dataset-snapshot
make release-contracts
```

`bootstrap-opportunities` runs scheduled scrapers, quality scoring, dedup reporting, and embedding rebuild. `seed-test-data` is intentionally excluded from the production bootstrap path; it is for local, CI, staging, or demo environments only.

## 17) Recruiter / Reviewer Checklist
If you are evaluating engineering depth, inspect:
- CI gate design and release policy workflows
- ranking mode architecture and telemetry loop
- security middleware and auth audit model
- hidden admin RBAC/TOTP implementation
- benchmark artifacts and reproducibility scripts

## 18) README Maintenance Policy
This README is release facing documentation. It should be updated whenever there is a major change to:
- architecture
- ML/ranking behavior
- security model
- deployment/reliability controls
- measurable product outcomes
