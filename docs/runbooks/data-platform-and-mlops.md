# Data Platform And MLOps Runbook

## Deployment

1. Production dependencies are managed services:
   - MongoDB Atlas for OLTP (`MONGODB_URL` must not point at localhost).
   - Managed Redis or Upstash for cache, rate limits, and online features.
   - Managed ClickHouse or a production ClickHouse cluster for marts.
   - S3 or MinIO with bucket versioning for model artifacts.
   - Prometheus, Alertmanager, and Grafana with live delivery configured.
2. Local compose remains for development only:
   - `mongo`
   - `redis`
   - `clickhouse`
   - `minio`
   - `metabase` or another BI surface pointed at ClickHouse
   - `prometheus`
   - `grafana`
3. Set backend secrets:
   - `MONGODB_URL`
   - `REDIS_URL`
   - `ANALYTICS_WAREHOUSE_CLICKHOUSE_*`
   - `MLOPS_MODEL_ARTIFACT_S3_*`
   - `LEARNED_RANKER_ARTIFACT_URI`
   - `LEARNED_RANKER_ARTIFACT_CHECKSUM_SHA256`
   - `LLM_API_KEY` and model endpoint
   - `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`
   - `SMTP_USER` / `SMTP_PASSWORD`
   - `MLOPS_ALERT_SLACK_WEBHOOK_URL` or `MLOPS_ALERT_PAGERDUTY_ROUTING_KEY`
4. Run backend startup health checks. Production boot will now fail if:
   - learned-ranker artifact cannot be downloaded
   - checksum verification fails
   - learned-ranker dependencies cannot load the artifact
   - ClickHouse production settings are missing while warehouse export is enabled
   - embedding service is degraded and policy forbids fallback
   - MongoDB or Redis points at localhost
   - model artifact S3/MinIO credentials are absent
   - LLM, OAuth, SMTP, or alert delivery secrets are absent
5. Before release, run:
   - `LEARNED_RANKER_ENABLED=true python backend/scripts/check_learned_ranker_production_smoke.py`
   - `python backend/scripts/check_warehouse_release_gate.py --json`
   - `python backend/scripts/check_ds_release_gates.py --fail-on-not-ready`
   - `python backend/benchmarks/run_assistant_quality_eval.py --fail-on-regression`
   - `python backend/scripts/check_production_infra_readiness.py --include-bi`
   - this fails if any `ANALYTICS_WAREHOUSE_REQUIRED_MARTS` table is missing or older than `ANALYTICS_WAREHOUSE_MAX_STALENESS_MINUTES`

## Warehouse Rebuild

1. Scheduled rebuild:
   - backend APScheduler enqueues `analytics.warehouse.rebuild` every `ANALYTICS_WAREHOUSE_REBUILD_INTERVAL_HOURS`
   - `.github/workflows/warehouse-mart-refresh.yml` rebuilds and gates marts every 6 hours when production secrets are configured
2. Manual rebuild:
   - `POST /api/v1/analytics/warehouse/rebuild`
   - `make warehouse-refresh`
3. Inspect latest exports:
   - `GET /api/v1/analytics/warehouse/exports`
4. Inspect freshness:
   - `GET /api/v1/analytics/warehouse/freshness`
5. Inspect marts:
   - `GET /api/v1/analytics/warehouse/marts`
   - `GET /api/v1/analytics/warehouse/marts/{mart_name}`
6. BI surfaces:
   - Grafana provisions `ops/grafana/vidyaverse-production-overview.json` with `ops/grafana/provisioning`
   - Metabase is included in production compose for ClickHouse marts
   - Managed Superset/Metabase can point at the same ClickHouse database and required `mart_*` tables

## Model Artifact Registry

1. Register a verified artifact:
   - `POST /api/v1/mlops/artifacts/register`
2. Approve or reject the verified artifact:
   - `POST /api/v1/mlops/artifacts/{artifact_id}/approve`
   - `POST /api/v1/mlops/artifacts/{artifact_id}/reject`
3. Compare versions before promotion:
   - `GET /api/v1/mlops/artifacts/compare?left_artifact_id=...&right_artifact_id=...`
4. Confirm the registry row exists:
   - `GET /api/v1/mlops/artifacts`
5. Activate only models with an approved artifact. `MODEL_REGISTRY_REQUIRE_APPROVED_FOR_ACTIVATION=true` blocks unapproved model activation.
6. Roll back artifact metadata if needed:
   - `POST /api/v1/mlops/artifacts/rollback`

## Backup / Restore

### MongoDB

- Backup:
  - `mongodump --uri "$MONGODB_URL" --archive="$(date -u +%Y%m%dT%H%M%SZ)-mongo.archive" --gzip`
- Restore:
  - `mongorestore --uri "$MONGODB_URL" --archive="$BACKUP_ARCHIVE" --gzip --drop`
  - `python backend/scripts/check_ds_release_gates.py --fail-on-not-ready`
- Drill:
  - `python backend/scripts/test_backup_restore_drill.py --execute`
  - Add `--require-mongodump` on runners where MongoDB Database Tools are installed to force archive-based proof.

### Model Artifacts

- MinIO / S3 bucket backup must be versioned.
- S3 backup copy:
  - `aws s3 sync "$MODEL_ARTIFACT_BUCKET" "$BACKUP_BUCKET/model-artifacts/$(date -u +%Y%m%dT%H%M%SZ)/" --only-show-errors`
- MinIO backup copy:
  - `mc mirror --overwrite "$MINIO_ALIAS/$MODEL_ARTIFACT_BUCKET" "$MINIO_BACKUP_ALIAS/model-artifacts"`
- For local cache recovery, delete `backend/storage/model_artifacts` and re-run artifact registration or service startup sync.
- Drill:
  - `MODEL_ARTIFACT_BUCKET=... python backend/scripts/test_backup_restore_drill.py --execute`

### Warehouse

- DuckDB/Parquet:
  - archive `backend/storage/warehouse`
- ClickHouse:
  - `clickhouse-client --query "BACKUP DATABASE vidyaverse TO S3('$CLICKHOUSE_BACKUP_URL', '$AWS_ACCESS_KEY_ID', '$AWS_SECRET_ACCESS_KEY')"`
  - `clickhouse-client --query "RESTORE DATABASE vidyaverse AS vidyaverse_restore FROM S3('$CLICKHOUSE_BACKUP_URL', '$AWS_ACCESS_KEY_ID', '$AWS_SECRET_ACCESS_KEY')"`

## Release Gates

- DS operating loop:
  - `python backend/scripts/check_ds_release_gates.py --fail-on-not-ready`
- Assistant quality:
  - `python backend/benchmarks/run_assistant_quality_eval.py --fail-on-regression`
- Champion/challenger:
  - `python backend/scripts/check_champion_challenger_gate.py --fail-on-not-ready`
- Warehouse:
  - `python backend/scripts/check_warehouse_release_gate.py --fail-on-not-ready`

These gates block stale features, drift alerts, parity regression, assistant failure rate, and missing staging/ML readiness.

## Production Proof

- Managed infra readiness:
  - `python backend/scripts/check_production_infra_readiness.py --include-bi`
- Backup/restore drill:
  - `python backend/scripts/test_backup_restore_drill.py --execute`
- Alert delivery:
  - `python backend/scripts/synthetic_alert_delivery_check.py`
- Weekly operational enforcement:
  - `.github/workflows/ops-operational-enforcement.yml`

## Dashboard Scorecards

- Refresh operating-loop metrics:
  - `GET /api/v1/mlops/operating-loop`
- Persist weekly scorecard:
  - `python backend/scripts/publish_weekly_ds_scorecard.py --dashboard-url "$GRAFANA_DS_DASHBOARD_URL" --dashboard-snapshot-path "$SNAPSHOT_PATH"`
- Automated review:
  - `.github/workflows/weekly-ds-operating-review.yml`
- Store rendered dashboard screenshots:
  - `scripts/capture_dashboard_screenshots.sh`

## Per-Slice Alerting

Per-slice ranker alerts are emitted for `domain`, `institution`, `geography`, and `segment`.
Grafana reads `ds_ranking_slice_rate{slice_type,slice_name,metric}`. Alertmanager routes `VidyaVerseRankerSliceApplyRateLow` to the MLOps receiver.

## Alert Response

- Assistant failures:
  - check `GET /api/v1/analytics/warehouse/overview`
  - inspect `GET /api/v1/security/events`
- Embedding degraded:
  - confirm the embedding provider and cache path
  - production should not be left on hash fallback
- Warehouse export failure:
  - inspect the latest `warehouse_export_runs` row
  - validate DuckDB write permissions and source Mongo collections
