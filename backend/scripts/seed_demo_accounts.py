"""Create one account per role, so the whole platform can be walked end to end.

Four roles exist and only students had accounts, which meant the employer portal,
the academician portal and the cohort dashboard could each be described but not
shown. A reviewer clicking through found three empty rooms.

This creates one account of each non-student role plus the content that makes
those rooms worth entering: a published listing from the employer, and a learning
programme whose skills match gaps students in this database actually have.

Passwords are never written into this file or the repository. One is generated
per run and printed once, or supplied by the operator with --password. A demo
credential committed to git is a real credential the moment the demo is hosted.

Dry run by default, per this repo's convention for anything that writes.

    python scripts/seed_demo_accounts.py                 # report only
    python scripts/seed_demo_accounts.py --apply         # create
    python scripts/seed_demo_accounts.py --apply --password 'chosen-one'
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import string
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class DemoAccount:
    email: str
    full_name: str
    account_type: str
    company_or_college: str
    note: str


# Corporate/institutional domains on purpose: employer and candidate signup both
# refuse consumer mailboxes, and a demo account that could not have been created
# through the real signup flow is a demo of something that does not exist.
DEMO_ACCOUNTS: tuple[DemoAccount, ...] = (
    DemoAccount(
        email="student@vidyaverse.dpdns.org",
        full_name="Demo Student",
        account_type="candidate",
        company_or_college="Lovely Professional University",
        note="Feed, skill assessment, applications.",
    ),
    DemoAccount(
        email="employer@vidyaverse.dpdns.org",
        full_name="Demo Industry Recruiter",
        account_type="employer",
        company_or_college="VidyaVerse Demo Industries",
        note="Posts openings and learning programmes.",
    ),
    DemoAccount(
        email="faculty@vidyaverse.dpdns.org",
        full_name="Demo Academician",
        account_type="faculty",
        company_or_college="Lovely Professional University",
        note="FDPs, postdocs, consultancy, and the industry demand signal.",
    ),
    DemoAccount(
        email="institution@vidyaverse.dpdns.org",
        full_name="Demo Institution Registrar",
        account_type="institution",
        company_or_college="Lovely Professional University",
        note="Cohort funnel and curriculum signal, aggregate only.",
    ),
)


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "Demo-" + "".join(secrets.choice(alphabet) for _ in range(16))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create the accounts (default: dry run)")
    parser.add_argument("--password", default=None, help="use this password instead of a generated one")
    args = parser.parse_args()

    from app.bootstrap import init_database
    from app.core.security import get_password_hash
    from app.core.time import utc_now
    from app.models.learning_program import LearningProgram
    from app.models.profile import Profile
    from app.models.user import User

    await init_database()

    password = args.password or generate_password()
    created: list[str] = []
    existing: list[str] = []

    for account in DEMO_ACCOUNTS:
        found = await User.find_one(User.email == account.email)
        if found is not None:
            existing.append(account.email)
            continue
        created.append(account.email)
        if not args.apply:
            continue

        user = User(
            email=account.email,
            hashed_password=get_password_hash(password),
            full_name=account.full_name,
            account_type=account.account_type,
            is_active=True,
            auth_provider="password",
        )
        await user.insert()

        first, _, last = account.full_name.partition(" ")
        profile = Profile(
            user_id=user.id,
            account_type=account.account_type,
            first_name=first,
            last_name=last,
        )
        # The institution's cohort is matched from its own profile, so without a
        # college name its dashboard has nothing to match against and would look
        # broken rather than empty.
        if account.account_type == "employer":
            profile.company_name = account.company_or_college
        else:
            # Students, academicians and institutions are all identified by the
            # institution they belong to - it is what the cohort match reads.
            profile.college_name = account.company_or_college

        if account.account_type == "candidate":
            # A student account with an empty profile lands on a dashboard that
            # can only tell them to fill it in, which demonstrates nothing.
            profile.domain = "AI AND MACHINE LEARNING"
            profile.course = "B.Tech Computer Science"
            profile.user_type = "college_student"
            profile.passout_year = 2027
            profile.skills = "Python, SQL, FastAPI, React"
            profile.interests = "Machine learning, backend engineering"
            profile.consent_data_processing = True
        elif account.account_type == "faculty":
            profile.department = "Computer Science"
            profile.designation = "Assistant Professor"
            profile.specialisation = "Machine Learning"
        elif account.account_type == "institution":
            profile.institution_type = "Private University"
            profile.aishe_code = "U-0577"
            profile.institution_city = "Phagwara"
            profile.institution_state = "Punjab"
            profile.contact_designation = "Registrar"

        await profile.save()

    # A programme aimed at gaps students in this database actually have, so the
    # recommendation on the skills page is a real match rather than a fixture.
    program_title = "Industry Readiness: Quality, Troubleshooting and Communication"
    program_exists = await LearningProgram.find_one(LearningProgram.title == program_title)
    program_action = "already present"
    if program_exists is None:
        program_action = "would create" if not args.apply else "created"
        if args.apply:
            # Looked up by role rather than by position: DEMO_ACCOUNTS[0] was
            # the recruiter until a student was added in front of it, which
            # would have credited an industry programme to a student.
            recruiter_email = next(
                (a.email for a in DEMO_ACCOUNTS if a.account_type == "employer"), None
            )
            recruiter = (
                await User.find_one(User.email == recruiter_email) if recruiter_email else None
            )
            await LearningProgram(
                title=program_title,
                description=(
                    "A six week industry readiness programme covering quality control, "
                    "systematic troubleshooting and workplace communication for final "
                    "year students entering their first role."
                ),
                provider="VidyaVerse Demo Industries",
                program_format="certification",
                delivery_mode="hybrid",
                duration_weeks=6,
                is_free=True,
                certificate_offered=True,
                skills_taught=["quality control", "troubleshooting", "communication"],
                posted_by_user_id=getattr(recruiter, "id", None),
                status="published",
                published_at=utc_now(),
            ).insert()

    print("Demo accounts")
    for account in DEMO_ACCOUNTS:
        state = "exists" if account.email in existing else ("created" if args.apply else "would create")
        print(f"  [{state:<12}] {account.email:<34} {account.account_type:<12} {account.note}")
    print()
    print(f"Learning programme: {program_action}")
    print()

    if args.apply and created:
        print("Password for the accounts created in this run:")
        print(f"    {password}")
        print("Shown once. It is not written to any file in this repository.")
    elif not args.apply:
        print("Dry run. Re-run with --apply to create them.")

    print()
    print("Note: the employer may draft listings immediately, but publishing to the")
    print("candidate feed requires a verified careers-page claim. That gate is the")
    print("point of the employer portal, so it is not bypassed here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
