# VidyaVerse - AI Opportunity Intelligence Platform

## Problem
Students discover internships, research roles, scholarships, and hackathons across fragmented portals. Most systems rely on keyword filtering, weak personalization, and manual shortlisting, which leads to low relevance and poor application conversion.

## What Is Implemented (Current State)
### AI/ML and Data Components
- Modular embedding service with `sentence-transformers` primary path and OpenAI embedding fallback support.
- NLP service for:
  - intent classification (`internships`, `research`, `scholarships`, `hackathons`)
  - NER extraction (`deadlines`, `locations`, `companies`, `eligibility`)
- Vector retrieval service with FAISS acceleration when available and NumPy cosine fallback.
- RAG service (`query -> retrieval -> structured insight generation`) exposed via `POST /api/v1/opportunities/ask-ai`.
- Recommendation stack with ranking modes: `baseline`, `semantic`, `ml`, `ab`.
- Interaction logging + experiment analytics endpoints (`CTR`, `lift`, experiment reports).
- Evaluation endpoints for ranking quality (`Precision@K`, `Recall@K`, `nDCG@K`, `MRR`) and LLM response quality.
- Semantic deduplication during scraper upserts using embedding similarity thresholds.
- MLOps endpoints/services for retraining and drift checks.

### Platform and Data Pipeline
- Multi-source ingestion: Ivy RSS + Indian opportunity sources.
- Resilient scraper runtime status + source-level run reports.
- Automatic updates via scheduler (default every 30 minutes).
- FastAPI backend + Next.js frontend with proxy routing.

## What Is Still Missing (High Impact Next)
- Production experiment data: interaction collections are currently empty, so no real A/B lift can be claimed yet.
- Harder offline benchmark dataset: current synthetic benchmark is too easy and does not separate baseline vs semantic quality.
- CI quality gates for metric regression and latency budgets.
- Real-time observability dashboard (p95 latency trend, scrape freshness SLA, experiment significance).
- Trained/activated ranking model versions in production (model registry currently empty).

## Architecture Diagram
```mermaid
flowchart LR
    A["Scrapers (Ivy + job/hackathon feeds)"] --> B["Ingestion Layer"]
    B --> C["Semantic Dedup (Embeddings)"]
    C --> D[("MongoDB Opportunities")]

    U["User Query"] --> E["Embedding Service"]
    U --> F["NLP Service (Intent + NER)"]
    D --> G["Vector Service (FAISS or NumPy)"]
    E --> G
    F --> G
    G --> H["Top-K Retrieval"]
    H --> I["RAG Service"]
    I --> J["Structured Insights JSON"]

    D --> K["Recommendation Service"]
    P["Profile + Interaction History"] --> K
    K --> L["Ranking Modes: baseline | semantic | ml | ab"]
    L --> M["Shortlist + Recommended Feed"]
    M --> N["Interaction Tracking"]

    N --> O["Experiment Analytics (CTR/Lift)"]
    N --> Q["MLOps Retraining"]
    Q --> R["Ranking Model Versions"]
    R --> K
    R --> S["Drift Detection"]
```

## Dataset Size (Verified Snapshot)
Snapshot date: **April 16, 2026**

- Opportunities: **199**
- Applications: **16**
- Opportunity interactions: **0**
- Experiments: **0**
- Experiment assignments: **0**
- Ranking model versions: **0**
- Drift reports: **0**

Source distribution for opportunities:
- `freshersworld`: 60
- `internshala`: 58
- `indeed_india`: 32
- `unstop`: 30
- `ivy_rss`: 14
- `hack2skill`: 5

## Latency (Local API Benchmark)
Benchmark date: **April 16, 2026**
Server: FastAPI on `127.0.0.1:8000`, 50 requests per endpoint.

| Endpoint | p50 | p95 | avg | max |
|---|---:|---:|---:|---:|
| `GET /api/v1/opportunities/?limit=30` | 116.75 ms | 242.38 ms | 152.05 ms | 513.28 ms |
| `GET /api/v1/opportunities/scraper-status` | 0.81 ms | 1.26 ms | 1.01 ms | 7.36 ms |

## Metric Gains (Offline Retrieval Benchmark)
Benchmark artifact: `backend/benchmarks/results.json` (12 queries, K=10).

| Metric | Baseline | Semantic | Gain |
|---|---:|---:|---:|
| Precision@10 | 0.108333 | 0.108333 | 0.00% |
| Recall@10 | 1.000000 | 1.000000 | 0.00% |
| nDCG@10 | 1.000000 | 1.000000 | 0.00% |
| MRR@10 | 1.000000 | 1.000000 | 0.00% |

Interpretation:
- The benchmark pipeline is implemented, but the current synthetic dataset is not challenging enough to show separation between ranking modes.
- Immediate next step: expand `gold.jsonl` with hard negatives and multi-relevant ambiguity to produce meaningful gains.

## A/B Lift (Current Production Data)
Current status: **not measurable yet**

- `opportunity_interactions` currently has no events, so CTR/apply/save lift vs baseline is unavailable.
- Instrumentation is implemented and endpoints are live:
  - `GET /api/v1/opportunities/experiments/ctr`
  - `GET /api/v1/opportunities/experiments/lift`
  - `GET /api/v1/experiments/{experiment_key}/report`

To unlock lift reporting:
1. Create and activate experiment variants.
2. Drive traffic to `baseline` and `semantic/ml` modes.
3. Log impressions + clicks/apply/save events.
4. Read lift and significance from experiment report endpoints.

## API Surface (Core AI/ML Endpoints)
- `GET /api/v1/opportunities/recommended/me?ranking_mode=baseline|semantic|ml|ab&query=...`
- `GET /api/v1/opportunities/shortlist/me?ranking_mode=baseline|semantic|ml|ab&query=...`
- `POST /api/v1/opportunities/ask-ai`
- `POST /api/v1/opportunities/interactions`
- `POST /api/v1/opportunities/evaluate-ranking`
- `POST /api/v1/opportunities/evaluate-llm`
- `GET /api/v1/opportunities/experiments/ctr`
- `GET /api/v1/opportunities/experiments/lift`
- `POST /api/v1/mlops/retrain`
- `GET /api/v1/mlops/models`
- `GET /api/v1/mlops/drift`

## Local Run
### Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Slim Domains (Preferred Workflow)
```bash
slim start web --port 3000
# https://web.test -> localhost:3000

slim start api --port 8000
# https://api.test -> localhost:8000
```

## Resume-Grade Positioning
Built an AI-powered opportunity intelligence platform with modular NLP/ML services (embeddings, intent+NER, vector retrieval, RAG), ranking experimentation (`baseline/semantic/ml/ab`), interaction analytics, and MLOps retraining/drift pipelines on a FastAPI + Next.js architecture.
