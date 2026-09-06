-- Where a demand table's numbers came from.
--
-- Ayush has no machine-readable posting feed. Thirty candidate sources were
-- fetched and read the way the extractor reads them: the councils and national
-- institutes publish PDF notices, the manufacturers run JavaScript careers
-- portals, and NCS is a search application that returns its own navigation.
-- Best yield across all thirty was seven rows, two of which were menu items.
--
-- So that sector's demand is derived from the competencies its published
-- standards require, which is a different kind of evidence and has to be
-- labelled as one. A share of postings and a weight from an occupational
-- standard are both legitimate; rendering them identically is how this repo
-- previously published a seeded constant as a measurement.
--
-- Existing rows default to 'postings' because that is what every one of them is.

ALTER TABLE app.skill_demand_snapshots
    ADD COLUMN IF NOT EXISTS basis text NOT NULL DEFAULT 'postings';
ALTER TABLE app.skill_demand_snapshots
    ADD COLUMN IF NOT EXISTS basis_note text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS skill_demand_snapshots_basis_idx
    ON app.skill_demand_snapshots (basis, domain_key, created_at DESC);
