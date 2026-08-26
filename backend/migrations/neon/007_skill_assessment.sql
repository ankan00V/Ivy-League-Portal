-- Skill assessment: what industry asks for, and what a student can do.
--
-- Two tables rather than one. Demand belongs to a domain and is rebuilt from
-- the live corpus on a schedule; an assessment belongs to a student and must
-- not change after the fact. An assessment therefore records which demand
-- snapshot it was scored against: a student told "you are missing Docker" who
-- returns to different advice a week later - because the corpus moved, not
-- because they did - has been given no advice at all.

CREATE TABLE IF NOT EXISTS app.skill_demand_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_mongo_id text UNIQUE,
    domain text NOT NULL,
    skills jsonb NOT NULL DEFAULT '[]'::jsonb,
    postings_analysed integer NOT NULL DEFAULT 0,
    postings_with_skills integer NOT NULL DEFAULT 0,
    corpus_version text,
    created_at timestamptz NOT NULL DEFAULT now(),
    extras jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Reads are always "the newest snapshot for this domain".
CREATE INDEX IF NOT EXISTS skill_demand_snapshots_domain_created_idx
    ON app.skill_demand_snapshots (domain, created_at DESC);
CREATE INDEX IF NOT EXISTS skill_demand_snapshots_created_idx
    ON app.skill_demand_snapshots (created_at DESC);

CREATE TABLE IF NOT EXISTS app.skill_assessments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_mongo_id text UNIQUE,
    user_id text NOT NULL,
    domain text NOT NULL,
    responses jsonb NOT NULL DEFAULT '{}'::jsonb,
    corroborated jsonb NOT NULL DEFAULT '{}'::jsonb,
    strengths jsonb NOT NULL DEFAULT '[]'::jsonb,
    gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
    readiness_score double precision NOT NULL DEFAULT 0,
    demand_snapshot_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    extras jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- The common read is a student's latest assessment.
CREATE INDEX IF NOT EXISTS skill_assessments_user_created_idx
    ON app.skill_assessments (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS skill_assessments_created_idx
    ON app.skill_assessments (created_at DESC);
