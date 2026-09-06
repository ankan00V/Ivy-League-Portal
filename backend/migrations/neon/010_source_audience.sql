-- Who a source, and therefore an opportunity, is for.
--
-- Every scraper here was pointed at student roles, and each other role's feed
-- was carved out of that one corpus by matching words in a title. Filtering
-- cannot add what the corpus does not contain: an FDP is advertised by AICTE,
-- not by a job board, so no keyword list over a job-board corpus produces one.
--
-- Audience travels seed -> discovered source -> opportunity. Existing rows are
-- left at 'student' because that is what they are, which keeps the student feed
-- - the only one that was ever working - unchanged.

ALTER TABLE app.discovered_sources
    ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'student';
ALTER TABLE app.company_seeds
    ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'student';
ALTER TABLE app.opportunities
    ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'student';

-- Feeds read "audience = X and status = active", so these are the index shapes.
CREATE INDEX IF NOT EXISTS opportunities_audience_status_idx
    ON app.opportunities (audience, opportunity_status);
CREATE INDEX IF NOT EXISTS discovered_sources_audience_idx
    ON app.discovered_sources (audience, status);
CREATE INDEX IF NOT EXISTS company_seeds_audience_idx
    ON app.company_seeds (audience);
