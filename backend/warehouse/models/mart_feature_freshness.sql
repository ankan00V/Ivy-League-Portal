SELECT
    traffic_type,
    COUNT(*) AS row_count,
    MAX(updated_at) AS latest_feature_at,
    MIN(updated_at) AS earliest_feature_at
FROM feature_store_rows
GROUP BY traffic_type
