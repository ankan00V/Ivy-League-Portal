-- Structured education and work history on profiles.
--
-- Both were flat, single-valued fields: college_name/course/passout_year and
-- current_job_role/total_work_experience/experience_summary. A student has a
-- school and a college, and usually several short internships, so the profile
-- could only ever hold the most recent of each.
--
-- jsonb rather than child tables: these are read and written whole, only ever
-- as part of a profile, and are never queried across users. The ODM already
-- persists lists of nested Pydantic models into jsonb (see ExperimentVariant).
--
-- The flat columns stay. Personalization and the ranker read college_name and
-- current_job_role, so they are kept in sync with the primary entry rather than
-- dropped.

ALTER TABLE app.profiles
    ADD COLUMN IF NOT EXISTS education_entries jsonb DEFAULT '[]'::jsonb;

ALTER TABLE app.profiles
    ADD COLUMN IF NOT EXISTS experience_entries jsonb DEFAULT '[]'::jsonb;

UPDATE app.profiles SET education_entries = '[]'::jsonb WHERE education_entries IS NULL;
UPDATE app.profiles SET experience_entries = '[]'::jsonb WHERE experience_entries IS NULL;
