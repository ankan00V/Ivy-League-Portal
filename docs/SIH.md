# SIH 2026 — what was added for the competition, and how to remove it

Everything built specifically for **SIH 2026, PS 26044** (Ministry of Ayush /
All India Institute of Ayurveda) is listed here so it can be reverted as one
piece rather than hunted for later.

**Convention.** SIH-only work is named `sih_*` (files) and committed under the
`sih` scope (`feat(sih): …`, `fix(sih): …`). Anything not on this list is
ordinary product work that happens to have been done during the same period,
and reverting SIH should not touch it.

---

## Files added for SIH

| path | what it is | safe to delete |
|---|---|---|
|  `docs/SIH.md` | this manifest | yes |
| `backend/app/services/sih_ayush_standards.py` | Ayush competency set: 18 competencies, 7 graduate roles, each with the document it is traceable to | yes |
| `backend/scripts/sih_seed_ayush_domain.py` | writes the Ayush demand snapshot from the above; dry-run by default | yes |
| `backend/tests/test_sih_ayush_standards.py` | tests for the competency set and the honesty of its labelling | yes |
| `backend/scripts/sih_seed_ayush_cohort.py` | the BAMS demo cohort; carries its own `--revert` | yes |

## Files modified for SIH

These are shared files, so **delete the marked block, do not revert the file** —
each carries other work from the same period.

| path | the SIH-specific part |
|---|---|
| `backend/app/models/skill_assessment.py` | `basis` and `basis_note` fields on `SkillDemandSnapshot` |
| `backend/migrations/neon/014_demand_snapshot_basis.sql` | adds those two columns; harmless to leave in place |
| `backend/app/services/skill_assessment_service.py` | `_rationale_for`, which stops a standards row being captioned "named in 0 live postings" |
| `backend/app/api/api_v1/endpoints/skills.py` | the `is_ayush_field` branch in `_resolve_domain` |

Two of those are worth keeping even if SIH is abandoned. `basis` on the snapshot
and `_rationale_for` both exist to stop a number of one provenance being
rendered in the typography of another, which is the defect this repo has had
twice. They cost nothing when only scraped domains exist.

## Database rows written for SIH

Written by the seed scripts, not by migrations, so they are removed with data
rather than with code.

| table | how to find them |
|---|---|
| `app.skill_demand_snapshots` | `WHERE basis = 'occupational_standard'` |
| `app.users`, `app.profiles`, `app.skill_assessments` | the seeded BAMS cohort — every account is on `@sih-demo.vidyaverse.invalid`; remove with `python backend/scripts/sih_seed_ayush_cohort.py --revert --apply` |

## Commits

The first landed before this convention was agreed and is scoped `ayush`
rather than `sih`; it is listed here so the manifest is complete.

- `83d2847` `feat(ayush): answer the problem statement in the sponsor's own field`

Subsequent SIH commits use the `sih` scope and can be listed with:

```bash
git log --oneline --grep '^[a-z]*(sih)'
```

## To remove SIH entirely

```bash
# 1. the data
python backend/scripts/sih_seed_ayush_cohort.py --revert --apply
#    then:
#    DELETE FROM app.skill_demand_snapshots WHERE basis = 'occupational_standard';

# 2. the files
git rm -r backend/app/services/sih_ayush_standards.py \
          backend/scripts/sih_seed_ayush_domain.py \
          backend/scripts/sih_seed_ayush_cohort.py \
          backend/tests/test_sih_ayush_standards.py \
          docs/SIH.md

# 3. the modified files - remove the marked blocks by hand, per the table above.
#    Do not `git checkout` them; they carry unrelated work.
```
