# Architecture (Publish Bundle)

```mermaid
flowchart LR
    A["Source Scrapers"] --> B["Ingestion + Normalization"]
    B --> C["Dedup + Enrichment"]
    C --> D[("MongoDB Core Tables")]

    U["Candidate Query"] --> E["Intent + NER"]
    U --> F["Embedding Service"]
    D --> G["Vector Retrieval (top-k)"]
    E --> G
    F --> G
    G --> H["RAG Template Registry"]
    H --> I["RAG Response + Safety/Judge Gates"]

    D --> J["Recommendation Service"]
    J --> K["Learned Ranker (ml mode default)"]
    K --> L["Feeds: Recommended + Shortlist"]
    L --> M["Interaction + Request Telemetry"]

    M --> N["Analytics Warehouse (daily/funnel/cohort)"]
    M --> O["Feature Store Rows (labels windowed)"]
    O --> P["Retraining + Model Lifecycle"]
    P --> K

    Q["Employer Portal"] --> R["Opportunity Lifecycle"]
    Q --> S["Candidate Pipeline States"]
    Q --> T["Recruiter Audit Logs"]

    V["Auth Endpoints"] --> W["Abuse Lock Policy"]
    V --> X["Structured Auth Audit Events"]
```

## Notes

- Production inference defaults to `ml` ranking mode with automatic request-level fallback only when the learned ranker fails.
- Ask-AI RAG output is governed by versioned templates (`prompt + retrieval settings + judge rubric`) with offline and online threshold gates.
- Warehouse and feature-store tables are materialized from raw interaction + request telemetry for reproducible DS analysis.
