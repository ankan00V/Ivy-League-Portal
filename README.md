# VidyaVerse

> AI-powered opportunity intelligence platform that helps students discover, prioritize, and act on internships, research roles, scholarships, and hackathons.

**Last updated:** April 28, 2026  
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
- **Production security posture:** cookie sessions, CSRF, CSP/Trusted Types, abuse locks, audit logs
- **Operational maturity:** CI release gates, incident artifacts, scheduled scorecards, synthetic checks
- **Privileged governance:** hidden admin control plane with strict single-admin + TOTP

## 4) Architecture
```mermaid
flowchart LR
    A["External Sources"] --> B["Scraper Ingestion"]
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
| Data | MongoDB, Redis |
| AI/ML | sentence-transformers, FAISS/NumPy retrieval, learned ranker |
| Observability/Ops | GitHub Actions, Prometheus metrics, Slack/PagerDuty hooks |
| Security | HttpOnly session cookies, CSRF middleware, CSP, Trusted Types, auth abuse controls |

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
- Background jobs with retry and dead-letter behavior.
- Staging integrated E2E framework and release-blocking checks.

### Security and Governance
- Cookie-first auth; localStorage token persistence removed.
- CSRF protection for unsafe requests under cookie auth.
- Security headers with strict CSP + Trusted Types controls.
- Auth lockout/audit instrumentation.
- Hidden admin control plane with TOTP and admin action auditing.

## 7) Metrics and Impact
### Data/Product Scale (snapshot: April 27, 2026)
- Opportunities: **331**
- Users: **323**
- Profiles: **320**
- Opportunity interactions: **20,987**
- Experiments: **3**
- Experiment assignments: **302**
- Ranking model versions: **47**
- Drift reports: **48**

### Offline retrieval quality
- Precision@5: **0.0667 -> 0.2000** (**+200%**)
- Recall@5: **0.3333 -> 1.0000** (**+200%**)
- nDCG@5: **0.3333 -> 1.0000** (**+200%**)
- MRR@5: **0.3333 -> 1.0000** (**+200%**)

### Real pilot lift (14-day window)
- CTR lift (`ml` vs baseline): **+58.21%**
- Apply-rate lift (`ml` vs baseline): **+153.11%**
- Save-rate lift (`ml` vs baseline): **+138.67%**

### Engineering quality signal
- Backend test suite: **77 passing tests** (latest local run)
- Frontend lint: **passing**
- Frontend production build: **passing**
- Security and release gates: **active in CI**

## 8) Reliability and Security Posture
- Session architecture favors HttpOnly cookie trust boundaries.
- CSRF origin/referer enforcement for unsafe methods.
- Strict CSP/Trusted Types controls integrated in security headers.
- Auth abuse lock policy with structured audit events.
- Production startup guardrails enforce secure host/CORS/CSP/cookie expectations.
- Privileged admin access segmented with dedicated auth path + TOTP + RBAC checks.

## 9) What Is In Progress
- Increase sustained real-user traffic volume for stronger statistical confidence.
- Complete full staging secret and ownership wiring across environments.
- Expand multi-role staging E2E matrix (success + failure + recovery paths).
- Promote strict production enforcement toggles once ops readiness is consistently stable.

## 10) Vision
Build VidyaVerse into a benchmark-grade Data Science + AI/ML + Full-Stack system where:
- ranking decisions are measurable and auditable,
- model promotion is policy-gated,
- product changes are experiment-driven,
- security and reliability remain first-class engineering constraints.

## 11) Quick Start
### Infrastructure
```bash
make up
```

### Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## 12) Key Configuration Areas
- Auth/Security: `AUTH_SESSION_COOKIE_*`, `AUTH_COOKIE_ONLY_MODE`, `CSRF_*`, `SECURITY_CSP_*`
- Admin bootstrap: `ADMIN_BOOTSTRAP_ENABLED`, `ADMIN_BOOTSTRAP_EMAIL`, `ADMIN_BOOTSTRAP_PASSWORD`, `ADMIN_TOTP_SECRET`
- MLOps alerts/incidents: `MLOPS_ALERT_SLACK_WEBHOOK_URL`, `MLOPS_ALERT_PAGERDUTY_ROUTING_KEY`, `MLOPS_INCIDENT_DEFAULT_OWNER`
- Parity gates: `MLOPS_PARITY_*`

Reference templates:
- `backend/.env.example`
- `backend/.env.production.example`

## 13) High-Value Code Paths
- Backend core: `backend/app`
- Frontend core: `frontend/src`
- CI/CD workflows: `.github/workflows`
- Runbooks: `docs/runbooks`
- Hidden admin security architecture: `docs/runbooks/hidden-admin-security-architecture.md`

## 14) Recruiter / Reviewer Checklist
If you are evaluating engineering depth, inspect:
- CI gate design and release policy workflows
- ranking mode architecture and telemetry loop
- security middleware and auth audit model
- hidden admin RBAC/TOTP implementation
- benchmark artifacts and reproducibility scripts

## 15) README Maintenance Policy
This README is release-facing documentation. It should be updated whenever there is a major change to:
- architecture
- ML/ranking behavior
- security model
- deployment/reliability controls
- measurable product outcomes
