# Data Platform And MLOps Runbook

## Deployment

1. Bring up stateful dependencies:
   - `mongo`
   - `redis`
   - `clickhouse`
   - `minio`
   - `prometheus`
   - `grafana`
2. Set backend secrets:
   - `MONGODB_URL`
   - `REDIS_URL`
   - `ANALYTICS_WAREHOUSE_CLICKHOUSE_*`
   - `MLOPS_MODEL_ARTIFACT_S3_*`
   - `LEARNED_RANKER_ARTIFACT_URI`
   - `LEARNED_RANKER_ARTIFACT_CHECKSUM_SHA256`
3. Run backend startup health checks. Production boot will now fail if:
   - learned-ranker artifact cannot be downloaded
   - checksum verification fails
   - embedding service is degraded and policy forbids fallback

## Warehouse Rebuild

1. Manual rebuild:
   - `POST /api/v1/analytics/warehouse/rebuild`
2. Inspect latest exports:
   - `GET /api/v1/analytics/warehouse/exports`
3. Inspect marts:
   - `GET /api/v1/analytics/warehouse/marts`
   - `GET /api/v1/analytics/warehouse/marts/{mart_name}`

## Model Artifact Registry

1. Register a verified artifact:
   - `POST /api/v1/mlops/artifacts/register`
2. Confirm the registry row exists:
   - `GET /api/v1/mlops/artifacts`
3. Activate only models with `serving_ready=true`.

## Backup / Restore

### MongoDB

- Backup:
  - `mongodump --uri "$MONGODB_URL" --archive=backup.archive --gzip`
- Restore:
  - `mongorestore --uri "$MONGODB_URL" --archive=backup.archive --gzip --drop`

### Model Artifacts

- MinIO / S3 bucket backup should be versioned.
- For local cache recovery, delete `backend/storage/model_artifacts` and re-run artifact registration or service startup sync.

### Warehouse

- DuckDB/Parquet:
  - archive `backend/storage/warehouse`
- ClickHouse:
  - snapshot the volume or use table export jobs

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
