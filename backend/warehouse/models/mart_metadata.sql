SELECT
    '{{ traffic_type }}' AS traffic_type,
    {{ lookback_days }} AS lookback_days,
    now() AS materialized_at
