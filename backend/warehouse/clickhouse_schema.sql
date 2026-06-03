-- VidyaVerse ClickHouse mart schema reference.
-- The exporter also creates these tables dynamically from DuckDB output; this file
-- gives operations a stable DDL contract for external provisioning and review.

CREATE DATABASE IF NOT EXISTS vidyaverse;

CREATE TABLE IF NOT EXISTS vidyaverse.mart_daily_metrics (
    date String,
    metric_type String,
    traffic_type String,
    ranking_mode String,
    experiment_key String,
    experiment_variant String,
    request_kind String,
    metrics String,
    created_at DateTime64(6, 'UTC'),
    updated_at DateTime64(6, 'UTC')
) ENGINE = MergeTree
ORDER BY (date, traffic_type, metric_type);

CREATE TABLE IF NOT EXISTS vidyaverse.mart_funnel_metrics (
    date String,
    traffic_type String,
    ranking_mode String,
    experiment_key String,
    experiment_variant String,
    stage_counts String,
    rates String,
    metadata String,
    created_at DateTime64(6, 'UTC'),
    updated_at DateTime64(6, 'UTC')
) ENGINE = MergeTree
ORDER BY (date, traffic_type, ranking_mode, experiment_variant);

CREATE TABLE IF NOT EXISTS vidyaverse.mart_cohort_metrics (
    cohort_date String,
    days_since_cohort Int64,
    traffic_type String,
    users_in_cohort Int64,
    active_users Int64,
    applying_users Int64,
    retention_rate Float64,
    apply_rate Float64,
    created_at DateTime64(6, 'UTC'),
    updated_at DateTime64(6, 'UTC')
) ENGINE = MergeTree
ORDER BY (cohort_date, days_since_cohort, traffic_type);

CREATE TABLE IF NOT EXISTS vidyaverse.mart_feature_freshness (
    traffic_type String,
    row_count Int64,
    latest_feature_at DateTime64(6, 'UTC'),
    earliest_feature_at DateTime64(6, 'UTC')
) ENGINE = MergeTree
ORDER BY (traffic_type);

CREATE TABLE IF NOT EXISTS vidyaverse.mart_parity_scorecard (
    ranking_mode String,
    ctr Float64,
    apply_rate Float64,
    latency_mean_ms Float64,
    failure_rate Float64
) ENGINE = MergeTree
ORDER BY (ranking_mode);

CREATE TABLE IF NOT EXISTS vidyaverse.mart_training_dataset (
    row_key String,
    date String,
    user_id String,
    opportunity_id String,
    ranking_mode String,
    experiment_key String,
    experiment_variant String,
    traffic_type String,
    rank_position Int64,
    match_score Float64,
    features String,
    labels String,
    source_event_id String,
    created_at DateTime64(6, 'UTC'),
    updated_at DateTime64(6, 'UTC')
) ENGINE = MergeTree
ORDER BY (date, row_key);

CREATE TABLE IF NOT EXISTS vidyaverse.mart_ranking_slice_metrics (
    date String,
    ranking_mode String,
    experiment_variant String,
    impressions Float64,
    clicks Float64,
    applies Float64,
    ctr Float64,
    apply_rate Float64
) ENGINE = MergeTree
ORDER BY (date, ranking_mode, experiment_variant);

CREATE TABLE IF NOT EXISTS vidyaverse.mart_metadata (
    traffic_type String,
    lookback_days Int64,
    materialized_at DateTime64(6, 'UTC')
) ENGINE = MergeTree
ORDER BY (materialized_at);
