-- Structured accomplishments, replacing four free-text columns.
--
-- achievements / certificates / projects / responsibilities were single
-- textareas, so nothing downstream could read a project's date range, a
-- certificate's expiry, or the issuer of an award without parsing prose. The
-- old columns are deliberately left in place: they still hold what users typed
-- before this, and dropping them would destroy that content. They are migrated
-- opportunistically, not automatically, because a paragraph cannot be split
-- into entries reliably enough to do it behind the user's back.
--
-- jsonb, matching education_entries/experience_entries from 005.

ALTER TABLE app.profiles
    ADD COLUMN IF NOT EXISTS project_entries jsonb DEFAULT '[]'::jsonb;

ALTER TABLE app.profiles
    ADD COLUMN IF NOT EXISTS certification_entries jsonb DEFAULT '[]'::jsonb;

ALTER TABLE app.profiles
    ADD COLUMN IF NOT EXISTS honor_entries jsonb DEFAULT '[]'::jsonb;

ALTER TABLE app.profiles
    ADD COLUMN IF NOT EXISTS volunteer_entries jsonb DEFAULT '[]'::jsonb;

-- Existing rows carry SQL NULL rather than the default, since ADD COLUMN with a
-- DEFAULT only backfills on newer Postgres and the ODM expects a list.
UPDATE app.profiles SET project_entries = '[]'::jsonb WHERE project_entries IS NULL;
UPDATE app.profiles SET certification_entries = '[]'::jsonb WHERE certification_entries IS NULL;
UPDATE app.profiles SET honor_entries = '[]'::jsonb WHERE honor_entries IS NULL;
UPDATE app.profiles SET volunteer_entries = '[]'::jsonb WHERE volunteer_entries IS NULL;
