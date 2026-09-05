"""The one paragraph each role opens the product to read.

Four dashboards, four different jobs, one shared problem: each of them ends in a
table, and a table is where the reader's work starts rather than where it ends.
A student sees a readiness score and eleven gap rows and has to decide which two
to act on. A registrar sees fifteen curriculum rows and has to decide what to
put to an academic council. The arithmetic was the easy half.

So each function here takes the measurements a dashboard already computed,
decides whether there is enough of them to say anything, and asks
`grounded_ai.GroundedNarrator` for the reading. What comes back is verified
against the numbers that went in, and if it cannot be verified the caller still
gets a true sentence built in Python. Three outcomes, never an error page:

    refused        - below the evidence floor, and it names what is missing.
    deterministic  - the model was unavailable or wrong; the facts still speak.
    llm            - the model's reading, with every number checked.

The floors are not new. They are the same ones the underlying services already
enforce - a cohort under five, a coverage figure under three assessments - and
they are repeated here because prose is exactly how a floor gets walked around.
A paragraph asserting a trend over two students reads far more confidently than
the two-row table it was written from.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.grounded_ai import GroundedAnswer, grounded_narrator

logger = logging.getLogger(__name__)

#: Gap rows a student needs before a plan is worth writing. Below this the
#: honest advice is "finish the assessment", which the deterministic branch says.
MIN_GAPS_FOR_PLAN = 3

#: Skills a recruiter must have measured supply for before scarcity is readable.
MIN_SCARCITY_ROWS = 3

#: Curriculum rows before an institution is told what to change. A syllabus
#: revision is a year of somebody's work; two rows is not a mandate for it.
MIN_SIGNAL_ROWS = 4

#: Demand rows before an academician is shown where their teaching sits.
MIN_DEMAND_ROWS = 5


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


# --------------------------------------------------------------------------
# Student
# --------------------------------------------------------------------------

_STUDENT_PROMPT = """
You are advising one student on what to do next with their time, using their own
skill assessment against live hiring demand on this platform.

They already know their readiness score and can see their gap list. Do not read
it back to them. Tell them which two or three gaps actually change their odds
and why, in the order they should attack them - a skill that appears in a large
share of live postings and which they cannot evidence is worth more of their
term than one that appears rarely.

Be concrete about effort. Say what "closing" a gap looks like for a student who
has a semester, not a career. Where a learning programme in the data teaches the
skill, name it exactly as given. If their readiness is low, say so kindly and
without softening the number.
""".strip()


async def student_readiness_plan(
    *,
    readiness: float,
    gaps: list[dict[str, Any]],
    strengths: list[dict[str, Any]],
    programmes: list[dict[str, Any]],
    domain: Optional[str] = None,
) -> GroundedAnswer:
    """What this student should do next, ranked by what moves their odds."""
    if len(gaps) < MIN_GAPS_FOR_PLAN:
        return GroundedAnswer(
            headline="Not enough of your assessment is finished to plan from.",
            paragraphs=[
                "A plan built on one or two answers would be a guess dressed up as advice. "
                "Finish the skill assessment and this becomes a ranked plan against live demand "
                "in your domain."
            ],
            actions=["Complete the skill assessment."],
            source="refused",
            refusal=f"{len(gaps)} gap(s) identified; {MIN_GAPS_FOR_PLAN} needed.",
        )

    top = sorted(gaps, key=lambda row: -float(row.get("demand_share") or 0))[:3]
    lead = top[0]
    fallback = GroundedAnswer(
        headline=(
            f"{lead.get('skill', 'One skill')} is your highest-value gap: "
            f"{_pct(lead.get('demand_share'))} of live postings ask for it."
        ),
        paragraphs=[
            "These gaps are ranked by how often employers currently ask for the skill, not by "
            "how far you are from it. A skill you are close to but nobody advertises will not "
            "change your outcomes; one that appears across the market will.",
            "Your readiness score moves as you evidence skills in the assessment, so the "
            "fastest visible progress comes from the skills you have partly used already.",
        ],
        actions=[f"Work on {row.get('skill')} ({_pct(row.get('demand_share'))} of postings)." for row in top],
        source="deterministic",
    )

    return await grounded_narrator.narrate(
        system_prompt=_STUDENT_PROMPT,
        facts={
            "readiness_score": round(float(readiness or 0), 1),
            "domain": domain,
            "gaps": [
                {
                    "skill": row.get("skill"),
                    "demand_share": row.get("demand_share"),
                    "your_level": row.get("level"),
                }
                for row in gaps[:10]
            ],
            "strengths": [row.get("skill") for row in strengths[:6]],
            "learning_programmes": [
                {"title": row.get("title"), "skills_taught": row.get("skills_taught")}
                for row in programmes[:4]
            ],
        },
        fallback=fallback,
    )


# --------------------------------------------------------------------------
# Industry / employer
# --------------------------------------------------------------------------

_EMPLOYER_PROMPT = """
You are advising a recruiter on whether the roles they are trying to fill are
fillable, using measured demand across live postings against measured supply in
the assessed candidate pool.

The distinction that matters and that no job board gives them: a skill with high
demand and near-zero supply is not a sourcing problem, it is a requirement
problem. Tell them plainly which of their skills fall into each case, and what
the honest response is - pay for it, train for it, or drop it from the
requirement list.

Supply figures are proportions over an anonymous pool. Never write about an
individual candidate, and never suggest the recruiter could be shown one.

If they have listings with no applicants, connect that to the scarcity data
where the data supports it, and say when it does not.
""".strip()


async def employer_market_read(
    *,
    scarcity: list[dict[str, Any]],
    candidates_assessed: int,
    listings: list[dict[str, Any]],
) -> GroundedAnswer:
    """Whether what this employer is asking for exists in the market."""
    if len(scarcity) < MIN_SCARCITY_ROWS:
        return GroundedAnswer(
            headline="Not enough of the candidate pool has been assessed to read the market.",
            paragraphs=[
                "Supply figures here are proportions of candidates who have completed a skill "
                "assessment. Until enough have, a single person moves every percentage on this "
                "page, and advice built on that would be worse than no advice."
            ],
            actions=["Check back as the assessed pool grows."],
            source="refused",
            refusal=f"{len(scarcity)} skill(s) have a readable supply figure; {MIN_SCARCITY_ROWS} needed.",
        )

    scarce = [row for row in scarcity if float(row.get("supply") or 0) < 0.3]
    plentiful = [row for row in scarcity if float(row.get("supply") or 0) >= 0.6]
    cold = [row for row in listings if int(row.get("applications") or 0) == 0]

    if scarce:
        lead = scarce[0]
        headline = (
            f"{lead.get('skill', 'One skill')} is scarce: {_pct(lead.get('demand_share'))} of "
            f"postings ask for it, {_pct(lead.get('supply'))} of assessed candidates can evidence it."
        )
    else:
        headline = "Nothing you are asking for is scarce in the assessed pool."

    paragraphs = [
        "Demand is the share of live postings naming a skill, which is your competition. Supply "
        "is the share of assessed candidates who can evidence it. A wide gap between the two is "
        "a requirement you will pay for, wait for, or have to train.",
    ]
    if plentiful:
        paragraphs.append(
            f"{plentiful[0].get('skill')} is widely available at {_pct(plentiful[0].get('supply'))}, "
            "so it is not what is holding a search up."
        )
    fallback = GroundedAnswer(
        headline=headline,
        paragraphs=paragraphs,
        actions=(
            [f"Reconsider or fund {row.get('skill')} — supply {_pct(row.get('supply'))}." for row in scarce[:2]]
            + ([f"{len(cold)} listing(s) have no applicants; review the requirement list."] if cold else [])
        ),
        source="deterministic",
    )

    return await grounded_narrator.narrate(
        system_prompt=_EMPLOYER_PROMPT,
        facts={
            "candidates_assessed": candidates_assessed,
            "skills": [
                {
                    "skill": row.get("skill"),
                    "demand_share": row.get("demand_share"),
                    "supply": row.get("supply"),
                    "verdict": row.get("verdict"),
                }
                for row in scarcity[:10]
            ],
            "listings_with_no_applicants": [row.get("title") for row in cold[:5]],
            "total_listings": len(listings),
        },
        fallback=fallback,
    )


# --------------------------------------------------------------------------
# Institution
# --------------------------------------------------------------------------

_INSTITUTION_PROMPT = """
You are writing for the person at an institution who has to take this to an
academic council or an accreditation panel: a registrar, a dean, an IQAC
coordinator.

They have two things nobody else has together - what industry is currently
advertising for, and what their own students can evidence. Your job is to turn
that crossing into an argument they can defend in a room, not a summary.

Say which specific gaps justify a curriculum change and why, and be equally
clear about where their cohort is already ahead of local demand, because that is
a place not to spend a year of somebody's work.

The funnel says where students stop progressing. If they stop before applying,
that is a placement-cell problem and not a syllabus problem; say which one the
data points to.

Coverage is measured only over students who took the assessment. Never describe
it as a share of the whole cohort.
""".strip()


async def institution_curriculum_brief(
    *,
    signal: list[dict[str, Any]],
    funnel: list[dict[str, Any]],
    cohort_size: int,
    students_assessed: int,
    institution: Optional[str] = None,
) -> GroundedAnswer:
    """The argument an institution can take to an academic council."""
    if len(signal) < MIN_SIGNAL_ROWS:
        return GroundedAnswer(
            headline="Not enough of your cohort has been assessed to argue for a syllabus change.",
            paragraphs=[
                "Coverage is measured against students who completed the assessment, and a skill "
                "is only reported once enough of them answered on it. Below that the percentage "
                "is noise with a decimal point, and a department would be asked to change a "
                "syllabus on the strength of two answers."
            ],
            actions=["Encourage more of the cohort to complete the skill assessment."],
            source="refused",
            refusal=f"{len(signal)} readable curriculum row(s); {MIN_SIGNAL_ROWS} needed.",
        )

    widest = sorted(signal, key=lambda row: -float(row.get("gap") or 0))[:3]
    ahead = [row for row in signal if float(row.get("gap") or 0) < 0]
    lead = widest[0]

    biggest_drop = None
    for stage in funnel:
        conversion = stage.get("conversion_from_previous")
        if conversion is None:
            continue
        if biggest_drop is None or float(conversion) < float(biggest_drop.get("conversion_from_previous") or 1):
            biggest_drop = stage

    paragraphs = [
        f"Industry asks for {lead.get('skill')} in {_pct(lead.get('demand_share'))} of live postings "
        f"in your domain; {_pct(lead.get('coverage'))} of your assessed students can evidence it. "
        "That difference is the curriculum argument - either number alone is trivia.",
    ]
    if biggest_drop is not None:
        paragraphs.append(
            f"Your cohort thins most at \"{biggest_drop.get('label')}\", carrying "
            f"{_pct(biggest_drop.get('conversion_from_previous'))} of the previous stage. "
            "Where students stop tells you whether this is a teaching problem or a placement-cell one."
        )
    if ahead:
        paragraphs.append(
            f"Your students are ahead of local demand on {ahead[0].get('skill')}, which is a reason "
            "not to spend more teaching time there."
        )

    fallback = GroundedAnswer(
        headline=(
            f"{lead.get('skill')} is your widest curriculum gap: {_pct(lead.get('demand_share'))} "
            f"of postings against {_pct(lead.get('coverage'))} of assessed students."
        ),
        paragraphs=paragraphs,
        actions=[
            f"Put {row.get('skill')} to the academic council — demand {_pct(row.get('demand_share'))}, "
            f"coverage {_pct(row.get('coverage'))}."
            for row in widest[:3]
        ],
        source="deterministic",
    )

    return await grounded_narrator.narrate(
        system_prompt=_INSTITUTION_PROMPT,
        facts={
            "institution": institution,
            "cohort_size": cohort_size,
            "students_assessed": students_assessed,
            "curriculum_signal": [
                {
                    "skill": row.get("skill"),
                    "industry_demand_share": row.get("demand_share"),
                    "student_coverage": row.get("coverage"),
                    "gap": row.get("gap"),
                    "students_assessed_on_it": row.get("students_assessed"),
                }
                for row in signal[:12]
            ],
            "funnel": [
                {
                    "stage": stage.get("label"),
                    "count": stage.get("count"),
                    "conversion_from_previous": stage.get("conversion_from_previous"),
                }
                for stage in funnel
            ],
        },
        fallback=fallback,
    )


# --------------------------------------------------------------------------
# Academician
# --------------------------------------------------------------------------

_FACULTY_PROMPT = """
You are writing for a working academic - someone who teaches a subject and also
has their own research and development to keep up.

Two things are in front of them: what industry is currently advertising for in
their field, and the programmes, fellowships and calls open to them right now.

Connect the two. Which of the live demand skills does their department plausibly
already teach, and which would need a new module or a lab? Where a programme in
the data would help them teach a skill that is in demand, say so and name the
programme exactly as given.

Deadlines matter more to this reader than to any other, because a fellowship
they hear about late is one they cannot apply for. If a deadline is near, lead
with it.

Do not tell them how to teach. Tell them what has changed in the market they
are teaching into.
""".strip()


async def faculty_field_brief(
    *,
    demand: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    department: Optional[str] = None,
    specialisation: Optional[str] = None,
) -> GroundedAnswer:
    """What has changed in the market an academician teaches into."""
    if len(demand) < MIN_DEMAND_ROWS:
        return GroundedAnswer(
            headline="Not enough live demand data yet to say what has changed in your field.",
            paragraphs=[
                "The demand table is derived from postings currently live on this platform. Until "
                "enough of them mention skills in your field, any reading of it would be a claim "
                "about the corpus rather than about your subject."
            ],
            actions=["Check back as the corpus grows."],
            source="refused",
            refusal=f"{len(demand)} demand row(s); {MIN_DEMAND_ROWS} needed.",
        )

    top = demand[:3]
    dated = [row for row in opportunities if row.get("deadline")]
    dated.sort(key=lambda row: str(row.get("deadline")))

    paragraphs = [
        f"{top[0].get('skill')} appears in {_pct(top[0].get('share'))} of live postings in this "
        "corpus, which is the clearest signal of what your students will be asked for.",
        "These shares move as the corpus moves, so they are a reading of the current market "
        "rather than a permanent ranking of what matters in your subject.",
    ]
    if dated:
        paragraphs.append(
            f"The nearest dated item open to you is \"{dated[0].get('title')}\", closing "
            f"{dated[0].get('deadline')}."
        )

    fallback = GroundedAnswer(
        headline=f"{top[0].get('skill')} leads current demand at {_pct(top[0].get('share'))} of live postings.",
        paragraphs=paragraphs,
        actions=(
            [f"Review whether {row.get('skill')} is covered in your syllabus." for row in top[:2]]
            + ([f"Apply for \"{dated[0].get('title')}\" before {dated[0].get('deadline')}."] if dated else [])
        ),
        source="deterministic",
    )

    return await grounded_narrator.narrate(
        system_prompt=_FACULTY_PROMPT,
        facts={
            "department": department,
            "specialisation": specialisation,
            "industry_demand": [
                {"skill": row.get("skill"), "share_of_postings": row.get("share")}
                for row in demand[:12]
            ],
            "open_to_you": [
                {
                    "title": row.get("title"),
                    "type": row.get("opportunity_type"),
                    "deadline": row.get("deadline"),
                    "source": row.get("source"),
                }
                for row in opportunities[:8]
            ],
        },
        fallback=fallback,
    )
