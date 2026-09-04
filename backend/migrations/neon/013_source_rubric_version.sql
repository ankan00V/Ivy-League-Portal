-- Which rubric judged a source, so a fixed rule can reach the sources it broke.
--
-- The qualification batch only ever reads sources in 'discovered' or
-- 'qualified'. Nothing rejected is looked at again, so every fix to a scoring
-- rule has been retroactively inert: the sources the rule was wrong about stay
-- rejected forever, and the rejection reason on them names a fault that no
-- longer exists.
--
-- Existing rows get 0 rather than the current version. They were judged by
-- rubrics 1 and 2 and 0 is honestly "we do not know which", which is the answer
-- that makes them eligible for one re-examination. Defaulting them to the
-- current version would silently write off exactly the backlog this column is
-- for.

ALTER TABLE app.discovered_sources
    ADD COLUMN IF NOT EXISTS rubric_version integer NOT NULL DEFAULT 0;

-- The batch reads "rejected, under an older rubric", newest first.
CREATE INDEX IF NOT EXISTS discovered_sources_rubric_status_idx
    ON app.discovered_sources (status, rubric_version);
