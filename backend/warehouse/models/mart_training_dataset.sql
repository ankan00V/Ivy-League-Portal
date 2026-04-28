SELECT
    row_key,
    date,
    user_id,
    opportunity_id,
    ranking_mode,
    experiment_key,
    experiment_variant,
    traffic_type,
    rank_position,
    match_score,
    features,
    labels,
    source_event_id,
    created_at,
    updated_at
FROM feature_store_rows
ORDER BY date DESC
