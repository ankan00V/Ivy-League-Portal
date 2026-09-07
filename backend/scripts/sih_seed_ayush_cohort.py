"""A BAMS cohort, so the curriculum signal is about the sponsor's field.

Built for SIH 2026 PS 26044. See docs/SIH.md; `--revert` removes
everything this writes.

The institution dashboard crosses what a field requires against what a cohort
can evidence. Both halves have to exist. The Ayush demand table comes from
`sih_ayush_standards`; this is the other half - an Ayurveda college with BAMS
students who have taken the assessment.

**These students are fabricated and the code says so in three places.** Every
user carries a `sih-demo` marker in its email domain, every profile records the
seeding run, and every assessment is written with provenance so the cohort
count can exclude or label them. That is not decoration: this repo has twice
published figures that turned out to be seeded constants read back, and the
second time it was caught only because a provenance column existed.

What is *not* fabricated is the mechanism. Levels are derived from a stated
competence profile per student, then run through the real `analyse()` with real
corroboration against the real Ayush demand snapshot, exactly as a live
submission would be. The readiness scores are computed, not chosen.

    python scripts/sih_seed_ayush_cohort.py            # report only
    python scripts/sih_seed_ayush_cohort.py --apply
    python scripts/sih_seed_ayush_cohort.py --revert --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

#: Every account this script creates lives on this domain. It is the handle for
#: reverting, and it is visibly not a real college.
SIH_DEMO_DOMAIN = "sih-demo.vidyaverse.invalid"

COLLEGE = "Government Ayurveda College, Demo"

#: Competence profiles, not answers. Each names how far through the course the
#: student is and which areas they have actually practised; the answers are
#: derived from that below, so the shape of the cohort is stated openly rather
#: than hidden in a list of numbers.
@dataclass(frozen=True)
class DemoStudent:
    first: str
    last: str
    year: int
    #: Competencies this student has clinical or practical exposure to.
    practised: tuple[str, ...]
    #: Competencies they have studied but not practised.
    studied: tuple[str, ...]


COHORT: tuple[DemoStudent, ...] = (
    DemoStudent("Aarav", "Nair", 4, ("kayachikitsa", "panchakarma", "nadi pariksha"),
                ("dravyaguna", "swasthavritta", "rasashastra", "agada tantra")),
    DemoStudent("Diya", "Menon", 4, ("kayachikitsa", "swasthavritta", "yoga therapy"),
                ("panchakarma", "dravyaguna", "prasuti tantra")),
    DemoStudent("Rohan", "Kulkarni", 3, ("dravyaguna", "rasashastra"),
                ("kayachikitsa", "swasthavritta", "raw drug authentication")),
    DemoStudent("Ananya", "Iyer", 4, ("kayachikitsa", "panchakarma", "shalya tantra"),
                ("dravyaguna", "agada tantra", "swasthavritta")),
    DemoStudent("Kabir", "Deshmukh", 3, ("swasthavritta", "yoga therapy"),
                ("kayachikitsa", "dravyaguna", "nadi pariksha")),
    DemoStudent("Meera", "Pillai", 4, ("kayachikitsa", "nadi pariksha", "kaumarbhritya"),
                ("panchakarma", "swasthavritta", "shalakya tantra")),
    DemoStudent("Ishaan", "Reddy", 3, ("dravyaguna", "swasthavritta"),
                ("rasashastra", "kayachikitsa", "clinical research")),
    DemoStudent("Sara", "Joshi", 4, ("kayachikitsa", "prasuti tantra", "panchakarma"),
                ("dravyaguna", "nadi pariksha", "swasthavritta")),
    DemoStudent("Vivaan", "Bhat", 2, ("dravyaguna",),
                ("kayachikitsa", "swasthavritta", "rasashastra")),
    DemoStudent("Tara", "Sharma", 4, ("kayachikitsa", "swasthavritta", "panchakarma", "yoga therapy"),
                ("dravyaguna", "agada tantra", "medical documentation")),
    DemoStudent("Arjun", "Varma", 3, ("panchakarma", "kayachikitsa"),
                ("dravyaguna", "swasthavritta", "nadi pariksha")),
    DemoStudent("Nisha", "Gowda", 4, ("kayachikitsa", "dravyaguna", "nadi pariksha"),
                ("panchakarma", "swasthavritta", "shalya tantra")),
)

#: The proficiency scale the assessment uses. 3 is the "confident" threshold
#: every coverage figure on the platform is measured against.
PRACTISED, STUDIED, UNSEEN = 4, 2, 1


def answers_for(student: DemoStudent, skills: list[str]) -> dict[str, int]:
    """Turn a stated competence profile into assessment answers.

    Practised beats the confidence threshold, studied sits below it, and
    anything the student has met neither way is answered honestly as unseen.
    The industry competencies that no NCISM subject teaches therefore come back
    low for almost everyone - which is the finding, not a thumb on the scale.
    """
    levels: dict[str, int] = {}
    for skill in skills:
        if skill in student.practised:
            levels[skill] = PRACTISED
        elif skill in student.studied:
            levels[skill] = STUDIED
        else:
            levels[skill] = UNSEEN
    return levels


async def revert(apply: bool) -> int:
    from app.models.profile import Profile
    from app.models.skill_assessment import SkillAssessment
    from app.models.user import User

    users = [u for u in await User.find_all().to_list() if SIH_DEMO_DOMAIN in (u.email or "")]
    print(f"Found {len(users)} seeded account(s) on {SIH_DEMO_DOMAIN}.")
    if not apply:
        for u in users[:5]:
            print(f"  would delete {u.email}")
        print("\nDry run. Re-run with --apply to delete them.")
        return 0
    removed = 0
    for user in users:
        await SkillAssessment.find(SkillAssessment.user_id == user.id).delete()
        await Profile.find(Profile.user_id == user.id).delete()
        await user.delete()
        removed += 1
    print(f"Deleted {removed} account(s), with their profiles and assessments.")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--revert", action="store_true", help="delete everything this script created")
    args = parser.parse_args()

    from app.bootstrap import init_database

    await init_database()
    if args.revert:
        return await revert(args.apply)

    from app.core.security import get_password_hash
    from app.models.profile import Profile
    from app.models.skill_assessment import SkillAssessment
    from app.models.user import User
    from app.services.sih_ayush_standards import AYUSH_DOMAIN
    from app.services.skill_assessment_service import analyse, build_questionnaire
    from app.services.skill_demand import latest_snapshot

    snapshot = await latest_snapshot(AYUSH_DOMAIN)
    if snapshot is None:
        print(f"No demand snapshot for {AYUSH_DOMAIN!r}.")
        print("Run scripts/sih_seed_ayush_domain.py --apply first.")
        return 1

    skills = [q.skill for q in build_questionnaire(snapshot.skills)]
    print(f"Cohort:     {len(COHORT)} BAMS students at {COLLEGE}")
    print(f"Assessment: {len(skills)} competencies from the {AYUSH_DOMAIN} table")
    print(f"Accounts:   *@{SIH_DEMO_DOMAIN}  (the handle for --revert)")
    print()

    created = 0
    for student in COHORT:
        email = f"{student.first.lower()}.{student.last.lower()}@{SIH_DEMO_DOMAIN}"
        existing = await User.find_one(User.email == email)
        if existing is not None:
            print(f"  [exists ] {email}")
            continue
        levels = answers_for(student, skills)
        if not args.apply:
            practised = sum(1 for v in levels.values() if v >= 3)
            print(f"  [would  ] {email:52} year {student.year}  {practised}/{len(skills)} at or above confident")
            continue

        user = User(
            email=email,
            hashed_password=get_password_hash("sih-demo-account-no-login"),
            full_name=f"{student.first} {student.last}",
            account_type="candidate",
            is_active=True,
            auth_provider="password",
        )
        await user.insert()
        profile = Profile(
            user_id=user.id,
            account_type="candidate",
            first_name=student.first,
            last_name=student.last,
            college_name=COLLEGE,
            domain="Medicine",
            course="BAMS",
            course_specialization="Ayurveda",
            user_type="college_student",
            passout_year=2026 + (5 - student.year),
            consent_data_processing=True,
            onboarding_completed=True,
            # The evidence a claim is corroborated against.
            #
            # Without this every claim of "confident" was pulled back below the
            # threshold and the cohort read 0% on every competency including
            # the ones eight of twelve students had practised - corroboration
            # working exactly as designed, against a profile that recorded
            # nothing. A real fourth-year who has done a Panchakarma rotation
            # lists Panchakarma; seeding the claim without the evidence models
            # a student who does not exist.
            skills=", ".join(student.practised),
            interests="Ayurvedic clinical practice",
        )
        await profile.save()

        # The real analysis path, against the real snapshot, with real
        # corroboration. Only the answers are derived.
        result = analyse(
            domain=AYUSH_DOMAIN,
            responses=levels,
            demand_rows=snapshot.skills,
            profile=profile,
        )
        await SkillAssessment(
            user_id=user.id,
            domain=AYUSH_DOMAIN,
            responses=result.responses,
            corroborated=result.corroborated,
            strengths=[vars(item) for item in result.strengths],
            gaps=[vars(item) for item in result.gaps],
            readiness_score=result.readiness_score,
            demand_snapshot_id=str(snapshot.id),
        ).insert()
        created += 1
        print(f"  [created ] {email:52} readiness {result.readiness_score:5.1f}")

    print()
    if args.apply:
        print(f"Created {created} student(s) with assessments.")
        print("Remove them with:  python scripts/sih_seed_ayush_cohort.py --revert --apply")
    else:
        print("Dry run. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
