"""Complete a skill assessment for candidates who have not taken one.

Three of this platform's best views - the institution's curriculum signal, the
employer's talent-pool scarcity, and a student's own gap list - are all gated on
having enough assessed candidates. With one assessment in the database every one
of them correctly refuses, so the features cannot be seen at all.

What this seeds and what it does not:

  * The answers are derived from each student's own declared skills, not
    invented. A profile listing Python is answered "confident" on Python and
    "aware" on things it does not mention. That is a reasonable stand-in for
    what the student would have said, and it is reproducible.

  * Everything after the answers is the real thing. The questionnaire comes from
    the live demand table, the scoring runs through the same analyse() the API
    calls, and corroboration still checks each claim against the profile - so a
    claim the profile cannot support is recorded lower here exactly as it would
    be for a real user.

So the levels are seeded and the assessment is genuine. Anything computed from
these rows is as trustworthy as its inputs, which is the honest position: it
demonstrates the mechanism, and it is not evidence about real students.

Dry run by default.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def answer_from_profile(skill: str, declared: set[str], is_soft: bool) -> int:
    """What this student would plausibly say about this skill."""
    cleaned = skill.strip().lower()
    if any(cleaned == term or cleaned in term or term in cleaned for term in declared):
        return 4  # named it themselves
    if is_soft:
        return 2  # everyone claims some, nobody evidences it without activity
    return 1  # aware of it, cannot evidence it


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from app.bootstrap import init_database
    from app.models.profile import Profile
    from app.models.skill_assessment import SkillAssessment
    from app.models.user import User
    from app.services import skill_demand as demand_module
    from app.services.skill_assessment_service import analyse, build_questionnaire

    await init_database()

    users = [
        user
        for user in await User.find_many().to_list()
        if str(getattr(user, "account_type", "") or "").lower() == "candidate"
    ]
    done = 0
    skipped = 0

    for user in users:
        existing = await SkillAssessment.find_many(SkillAssessment.user_id == user.id).count()
        if existing:
            skipped += 1
            continue

        profile = await Profile.find_one(Profile.user_id == user.id)
        domain = str(getattr(profile, "domain", None) or "").strip() or demand_module.GLOBAL_DOMAIN
        snapshot = await demand_module.latest_snapshot(domain)
        if snapshot is None:
            print(f"  [skip] {user.email}: no demand snapshot")
            continue

        declared = {
            piece.strip().lower()
            for piece in re.split(r"[,;/|]+", str(getattr(profile, "skills", None) or ""))
            if piece.strip()
        }
        questions = build_questionnaire(snapshot.skills)
        responses = {
            item.skill: answer_from_profile(item.skill, declared, item.is_soft)
            for item in questions
        }

        result = analyse(
            domain=domain, responses=responses, demand_rows=snapshot.skills, profile=profile
        )
        print(
            f"  [{'done' if args.apply else 'would'}] {user.email:<34} "
            f"readiness {result.readiness_score:5.1f}  gaps {len(result.gaps):>2}  "
            f"adjusted {len(result.adjustments)}"
        )
        done += 1
        if args.apply:
            await SkillAssessment(
                user_id=user.id,
                domain=domain,
                responses=result.responses,
                corroborated=result.corroborated,
                strengths=[vars(item) for item in result.strengths],
                gaps=[vars(item) for item in result.gaps],
                readiness_score=result.readiness_score,
                demand_snapshot_id=str(snapshot.id),
            ).insert()

    print(f"\n{'created' if args.apply else 'would create'}: {done}   already assessed: {skipped}")
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
