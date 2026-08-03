# Student Beta and Learned-Ranker Rollout

This runbook governs the move from infrastructure validation to a real-user
ranking experiment. It deliberately does not treat synthetic, Kaggle, or
Hugging Face data as ranking labels.

## Preconditions

- Recruit a small, consented candidate cohort (target: 20 students) and give
  each participant a normal production-like account.
- Confirm that impression, click, save, hide, apply, and application-outcome
  events are written with `traffic_type=real`.
- Keep the learned ranker shadow-only:
  - `LEARNED_RANKER_SHADOW_ENABLED=true`
  - `LEARNED_RANKER_STAGED_ROLLOUT_ENABLED=false`
  - `LEARNED_RANKER_STAGED_ROLLOUT_PERCENT=0`
- Verify that the semantic baseline remains available and that the model
  artifact, feature contract, and release gates are healthy.

## During the Beta

1. Ask participants to browse opportunities naturally; do not manufacture
   clicks, saves, or applies.
2. Record operational issues separately from ranking feedback. In particular,
   distinguish expired listings, eligibility mismatches, and page failures
   from relevance judgments.
3. Review source freshness, low-confidence review queues, duplicate rates,
   OTP failures, recommendation latency, and error alerts daily.
4. Publish a read-only telemetry report at the end of each observation window:

   ```bash
   cd backend
   venv/bin/python scripts/publish_ranker_rollout_report.py --days 7
   ```

   The report is evidence only. Zero or synthetic interactions must not be
   described as lift, statistical significance, or model quality.

## Training Gate

Do not train or activate a learned ranker until all of the following are true:

- At least `MLOPS_MIN_TRAINING_ROWS` real, labeled interaction rows exist
  (default: 200).
- Labels have matured past `MLOPS_LABEL_WINDOW_HOURS` (default: 72 hours).
- The sample includes both positive and negative outcomes rather than only
  impressions.
- Interaction volume and outcome rates are inspected by cohort so a single
  participant or source cannot dominate the dataset.
- Data-quality, feature freshness, drift, and release gates pass for the
  training window.

Never include records created by `bootstrap_ranking_pipeline.py` or
`simulate_persona_traffic.py` in the training or online-lift decision set.

## Staged Experiment

1. Train and evaluate a challenger from real interactions only.
2. Keep shadow evaluation enabled and inspect the champion/challenger report.
3. Enable `LEARNED_RANKER_STAGED_ROLLOUT_ENABLED` only after the challenger is
   approved by the model-activation policy.
4. Start with a small, stable cohort by setting
   `LEARNED_RANKER_STAGED_ROLLOUT_PERCENT`; use the configured semantic mode
   as the control.
5. Compare CTR, apply rate, freshness, latency p95, and failure rate over a
   completed observation window. The configured guardrails must remain green.
6. If a guardrail fails, stop increasing rollout immediately. The configured
   rollback policy must retain or restore the baseline before another trial.

## Evidence to Retain

- Cohort consent and recruitment record, without storing sensitive content in
  the repository.
- Real-traffic count and outcome distribution for every decision window.
- Generated rollout reports and the model artifact checksum.
- Approval/rollback decision, owner, timestamp, and guardrail rationale.

