-- Persist role track and placement so the feed can page and filter in SQL.
--
-- Both were computed in Python at serialization time, which meant answering
-- "how many technical roles are there" required loading every active row. That
-- is why the feed fetched all ~1500 listings at 3.36 MB per request and
-- exhausted a 5.5 GB monthly Postgres egress budget in roughly 1,600 page
-- loads.
--
-- As columns they can be filtered and counted in the query, so a page view
-- moves 12 rows instead of 1500.
--
-- Nullable on purpose: existing rows are backfilled by
-- scripts/backfill_opportunity_facets.py, and a row written before that ran
-- must not be mistaken for one classified as non-technical. Read paths treat
-- NULL as "not yet classified" and fall back to computing it.
ALTER TABLE app.opportunities
    ADD COLUMN IF NOT EXISTS role_track text,
    ADD COLUMN IF NOT EXISTS feed_categories text[] DEFAULT '{}';

-- Partial index: every feed query already filters opportunity_status='active',
-- and the retired rows are roughly a third of the table.
CREATE INDEX IF NOT EXISTS opportunities_role_track_active_idx
    ON app.opportunities (role_track)
    WHERE opportunity_status = 'active';

-- GIN because feed_categories is non-exclusive - a remote role in Bengaluru is
-- both 'india' and 'remote' - so lookups are array-containment, not equality.
CREATE INDEX IF NOT EXISTS opportunities_feed_categories_active_idx
    ON app.opportunities USING GIN (feed_categories)
    WHERE opportunity_status = 'active';
