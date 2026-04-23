# Gold Dataset Labeling Protocol (Ranking)

## Objective
Create a stable, versioned ranking-evaluation set with temporal holdout hygiene for offline quality gates.

## Record Schema
Each gold row must include:

- `query` (string): user intent phrasing.
- `relevant_ids` (array[string]): binary relevance IDs.
- `graded_relevance` (object, optional): `opportunity_id -> grade` where grade is 0-3.
- `split` (string): one of `train`, `validation`, `holdout`.
- `not_before` (ISO datetime, optional): minimum publish time for temporal filtering.
- `labeler` (string): annotator identifier.
- `labeled_at` (ISO datetime): label timestamp.
- `notes` (string, optional): rationale, edge cases, tie-break context.

## Relevance Scale
- `3`: directly matches domain, role intent, and seniority/scope.
- `2`: strong match but one axis is weaker (scope/domain/specificity).
- `1`: tangentially relevant.
- `0`: not relevant.

## Labeling Rules
- Keep at least 2 high-grade (`>=2`) items per query when available.
- Include hard negatives with lexical overlap to stress semantic ranking.
- Prefer paraphrased queries over keyword-only templates.
- Resolve disagreements via adjudication pass; keep rationale in `notes`.

## Temporal Holdout Rules
- Holdout opportunities must satisfy `published_at >= holdout_cutoff`.
- Holdout queries must use `split=holdout` and/or `not_before >= holdout_cutoff`.
- Never backfill labels from future snapshots into older holdout versions.

## Versioning
- Store datasets in `backend/benchmarks/data/`.
- Snapshot naming: `gold.<YYYYMMDD>.<version>.jsonl`.
- Update changelog entry in PR description with:
  - number of new queries
  - number of updated labels
  - holdout coverage delta
