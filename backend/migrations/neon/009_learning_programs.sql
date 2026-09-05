-- Industry-published learning programmes.
--
-- skills_taught is the column that matters: it is what matches a programme to
-- the gaps a student's assessment already found. A programme without it can be
-- listed but never recommended, so the API refuses to create one.

CREATE TABLE IF NOT EXISTS app.learning_programs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_mongo_id text UNIQUE,
    title text NOT NULL,
    description text NOT NULL,
    provider text NOT NULL,
    url text,
    program_format text NOT NULL DEFAULT 'course',
    delivery_mode text NOT NULL DEFAULT 'online',
    duration_weeks integer,
    is_free boolean NOT NULL DEFAULT true,
    cost_inr integer,
    certificate_offered boolean NOT NULL DEFAULT false,
    skills_taught text[] NOT NULL DEFAULT '{}',
    posted_by_user_id text,
    status text NOT NULL DEFAULT 'draft',
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    extras jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- The student-facing read is always "published, newest first".
CREATE INDEX IF NOT EXISTS learning_programs_status_created_idx
    ON app.learning_programs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS learning_programs_poster_idx
    ON app.learning_programs (posted_by_user_id, created_at DESC);
