WITH interaction_rollup AS (
    SELECT
        date,
        ranking_mode,
        experiment_variant,
        SUM(COALESCE(TRY_CAST(json_extract_string(to_json(metrics), '$.impressions') AS DOUBLE), 0)) AS impressions,
        SUM(COALESCE(TRY_CAST(json_extract_string(to_json(metrics), '$.clicks') AS DOUBLE), 0)) AS clicks,
        SUM(COALESCE(TRY_CAST(json_extract_string(to_json(metrics), '$.applies') AS DOUBLE), 0)) AS applies
    FROM analytics_daily
    WHERE metric_type = 'interaction'
    GROUP BY 1, 2, 3
)
SELECT
    date,
    ranking_mode,
    experiment_variant,
    impressions,
    clicks,
    applies,
    CASE WHEN impressions > 0 THEN clicks / impressions ELSE 0 END AS ctr,
    CASE WHEN impressions > 0 THEN applies / impressions ELSE 0 END AS apply_rate
FROM interaction_rollup
ORDER BY date DESC, ranking_mode ASC
