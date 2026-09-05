"""Who a source, and therefore an opportunity, is for.

Every scraper in this repo was pointed at student roles, and every role's feed
was then carved out of that one corpus by matching words in a title. That works
for students, because the corpus is theirs, and degrades for everyone else: the
academician feed was seven items out of nearly two thousand, and each of those
seven had to be rescued from a list where "Market Research Intern" matched
"research".

Filtering a corpus cannot add what the corpus does not contain. An FDP is
advertised by AICTE and NITTTR, not by a job board, so no keyword list over a
job-board corpus will ever produce one. The fix is upstream: a source knows who
it serves, and what it yields inherits that.

Audience travels source -> discovered source -> opportunity, so a feed becomes a
lookup on a column rather than a guess about a title. Legacy rows carry no
audience, and are treated as student rows: that is what they are, and it keeps
the student feed - the only one that was ever working - byte-identical.
"""

from __future__ import annotations

STUDENT = "student"
FACULTY = "faculty"
INSTITUTION = "institution"

KNOWN_AUDIENCES: frozenset[str] = frozenset({STUDENT, FACULTY, INSTITUTION})

#: What a row with no audience means. Every opportunity predating this column
#: came from a student-facing scraper, so this is a statement of fact rather
#: than a convenient default.
DEFAULT_AUDIENCE = STUDENT

AUDIENCE_LABELS: dict[str, str] = {
    STUDENT: "Students",
    FACULTY: "Academicians",
    INSTITUTION: "Institutions",
}


def normalise_audience(value: str | None) -> str:
    """Coerce to a known audience, falling back to student.

    Never raises. An unrecognised value on a scraped row should put that row in
    the student feed, where a human will see it, rather than drop it into a feed
    nobody reads or fail the whole extraction batch.
    """
    candidate = str(value or "").strip().lower()
    return candidate if candidate in KNOWN_AUDIENCES else DEFAULT_AUDIENCE


def audience_matches(row_audience: str | None, wanted: str) -> bool:
    return normalise_audience(row_audience) == normalise_audience(wanted)
