WITH request_metrics AS (
    SELECT
        ranking_mode,
        AVG(COALESCE(TRY_CAST(metrics.latency_mean_ms AS DOUBLE), 0)) AS latency_mean_ms,
        AVG(COALESCE(TRY_CAST(metrics.failure_rate AS DOUBLE), 0)) AS failure_rate
    FROM analytics_daily
    WHERE metric_type = 'request'
    GROUP BY 1
),
interaction_metrics AS (
    SELECT
        ranking_mode,
        AVG(COALESCE(TRY_CAST(metrics.ctr AS DOUBLE), 0)) AS ctr,
        AVG(COALESCE(TRY_CAST(metrics.apply_rate AS DOUBLE), 0)) AS apply_rate
    FROM analytics_daily
    WHERE metric_type = 'interaction'
    GROUP BY 1
)
SELECT
    COALESCE(request_metrics.ranking_mode, interaction_metrics.ranking_mode) AS ranking_mode,
    COALESCE(interaction_metrics.ctr, 0) AS ctr,
    COALESCE(interaction_metrics.apply_rate, 0) AS apply_rate,
    COALESCE(request_metrics.latency_mean_ms, 0) AS latency_mean_ms,
    COALESCE(request_metrics.failure_rate, 0) AS failure_rate
FROM request_metrics
FULL OUTER JOIN interaction_metrics
    ON request_metrics.ranking_mode = interaction_metrics.ranking_mode
ORDER BY ranking_mode ASC
