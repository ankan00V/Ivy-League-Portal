-- Audience on the registration, so a promoted source keeps producing for its
-- own feed.
--
-- Audience already travelled seed -> discovered source -> opportunity, and
-- migration 010 added those three columns. It missed the fourth hop. Once a
-- source is promoted the scheduled path stops reading DiscoveredSource and
-- reads ScraperRegistration instead, which had no audience at all - so every
-- row that path produced was written as a student row.
--
-- The consequence only appears after promotion, which is why it was invisible:
-- no faculty or institution source has ever been promoted, so the defect had
-- never had the chance to fire. It would have fired on the first one.

ALTER TABLE app.scraper_registrations
    ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'student';

-- Backfill from the source each registration was promoted from, rather than
-- leaving them all at the default. Existing rows are genuinely student rows,
-- but reading the value across rather than assuming it keeps the two tables
-- honest if that ever stops being true.
UPDATE app.scraper_registrations AS r
SET audience = s.audience
FROM app.discovered_sources AS s
WHERE r.discovered_source_id IS NOT NULL
  AND s.id::text = r.discovered_source_id
  AND r.audience IS DISTINCT FROM s.audience;

CREATE INDEX IF NOT EXISTS scraper_registrations_audience_idx
    ON app.scraper_registrations (audience, status);
