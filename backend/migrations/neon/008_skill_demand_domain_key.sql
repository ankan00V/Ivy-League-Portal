-- Match demand snapshots on a canonical domain key.
--
-- Profiles store the student's domain upper-cased ("AI AND MACHINE LEARNING");
-- opportunities store it title-cased ("AI and Machine Learning"). The exact
-- match between them never succeeded, so every student fell through to the
-- whole-market table while the UI explained that their domain had too few
-- postings - a wrong answer that looked exactly like a working feature.

ALTER TABLE app.skill_demand_snapshots
    ADD COLUMN IF NOT EXISTS domain_key text NOT NULL DEFAULT '';

-- Backfill existing rows rather than waiting for the next refresh, so the
-- feature is not silently degraded until then.
UPDATE app.skill_demand_snapshots
   SET domain_key = lower(btrim(domain))
 WHERE domain_key = '';

CREATE INDEX IF NOT EXISTS skill_demand_snapshots_key_created_idx
    ON app.skill_demand_snapshots (domain_key, created_at DESC);
