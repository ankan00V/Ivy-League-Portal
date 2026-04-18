# VidyaVerse Incident Runbook

## Alert Intake
1. Confirm alert source and severity (`warn` vs `page`) from Alertmanager.
2. Open Grafana dashboard `ops/grafana/vidyaverse-production-overview.json`.
3. Record UTC start time, impacted variant(s), and current mitigation status.

## Latency Spike
1. Validate `ranking_request_latency_ms` p95 and request error rate by `request_kind`.
2. Check if regression is isolated to a single experiment variant.
3. If only one variant is impacted, pause the experiment via `PATCH /api/v1/experiments/{key}` status=`paused`.
4. If all variants are impacted, rollback latest backend deploy and inspect DB/Redis saturation.

## Freshness SLA Breach
1. Check `/api/v1/opportunities/scraper-status` and latest scraper logs.
2. Trigger scraper job (`POST /api/v1/opportunities/trigger-scraper`) and monitor `opportunity_freshness_seconds`.
3. If scraper failures persist >15 minutes, fail over to cached recommendation mode and escalate ingestion owner.

## Experiment Regression
1. Open `/api/v1/experiments/{experiment_key}/report?conversion=click,apply,save&traffic_type=real`.
2. Verify `diagnostics.guardrails` and confirm significant negative lift (`p_value < alpha`, `diff < 0`).
3. If not auto-paused, manually pause experiment immediately.
4. Capture baseline vs variant impression counts and conversion deltas for postmortem.

## Sample Ratio Mismatch (SRM)
1. Confirm mismatch in report `diagnostics.srm` and Grafana impression split panel.
2. Rotate experiment salt only after pausing and documenting root cause.
3. Re-enable experiment only after assignment logic and traffic filters are validated.

## Post-Incident
1. Publish incident summary in `#mlops-alerts` with timeline and blast radius.
2. File follow-up issue for root cause and permanent fix.
3. Add missing regression test or alert rule if detection was late.
