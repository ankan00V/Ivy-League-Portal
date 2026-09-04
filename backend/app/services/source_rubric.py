"""The version of the rules a source was last judged by.

Every scoring bug this pipeline has had shared one consequence, and it was
always worse than the bug. A source rejected by a broken rule stays rejected:
the qualification batch only ever looks at sources in `discovered` or
`qualified`, so nothing rejected is ever asked again. Fixing the rule therefore
does nothing for the sources the rule was wrong about.

That has now happened three times.

  * `normalize_url` stripped `www.` and the stripped host was then used to
    fetch. Four of seven academic sources scored 36 on reachability. The README
    records that they "would have been rejected on every future run however good
    the site was" - which was true, and the reason was this, not the fetch bug.
  * `opportunity_density` counted jobs vocabulary only, capping every
    institution source at exactly 59.0 against a threshold of 60. NIRF and AIM
    both landed there.
  * Trust scored relevance against "student, fresher, stipend" and legitimacy
    against a list of corporate brand names, so a government research council
    scored 0 of 15 for not being a company, and cross-source validation scored 0
    of 10 for being the first source of its audience - a check no first source
    can ever satisfy.

Each fix shipped and changed nothing that was already rejected. So the fix
belongs here rather than in any one check: record which rubric judged a source,
and let a source judged by an older rubric be asked again.

Bump `QUALIFICATION_RUBRIC_VERSION` whenever a check's scoring changes in a way
that could turn a rejection into an acceptance. Do not bump it for a change that
can only reject more, and never bump it to force a re-run - a re-examination
costs a live fetch of every affected source.

Some rejections are not about the rubric at all. A domain that showed spam
signals or failed the SSRF guard is not a scoring mistake, and re-admitting it
on every version bump would walk the crawler back into exactly the places the
guard exists to keep it out of. `REEXAMINABLE_REJECTIONS` is therefore an
allow-list, not a deny-list: a reason has to be argued onto it.
"""

from __future__ import annotations

#: Increment when a scoring rule changes such that a previously rejected source
#: might now pass. History, so the reason for each re-examination survives:
#:   1 - the original rubric.
#:   2 - audience-aware opportunity_density (institution sources capped at 59.0).
#:   3 - audience-aware trust relevance, accredited-domain legitimacy, and
#:       cold-start cross-validation; audience-aware extraction vocabulary.
QUALIFICATION_RUBRIC_VERSION = 3

#: Rejection reasons whose verdict depends on the rubric, and which are
#: therefore worth asking again under a newer one. Matched on the prefix before
#: the colon, since these reasons carry a measured value after it.
REEXAMINABLE_REJECTIONS: frozenset[str] = frozenset(
    {
        # Scored too low overall - the most direct rubric verdict there is.
        "low_qualification_score",
        # The parser found little; an audience-aware extractor may find more.
        "low_extraction_confidence",
        "too_few_opportunities",
        # Transient by nature. A site that was down is not a bad site, and the
        # www fetch bug produced this reason for four sources that were fine.
        "reachability",
        "extraction_error",
        # Probation is judged on trust, which is one of the things that changed.
        "probation_failed",
    }
)

#: Never re-examined. Spam and the URL guard are safety verdicts, not scores.
PERMANENT_REJECTIONS: frozenset[str] = frozenset({"spam_signals", "blocked_url", "ssrf_blocked"})


def rejection_kind(reason: str | None) -> str:
    """The reason's stable prefix, without the measured value after the colon."""
    return str(reason or "").split(":", 1)[0].strip()


def is_reexaminable(reason: str | None, *, rubric_version: int | None) -> bool:
    """Whether a rejected source deserves another look under the current rubric.

    Two conditions, both required. The verdict has to be one a rubric could have
    got wrong, and the rubric that produced it has to be older than the current
    one. Without the second condition this would re-fetch every rejected source
    on every batch, which is a crawl of the whole rejection pile masquerading as
    a bug fix.
    """
    kind = rejection_kind(reason)
    if kind in PERMANENT_REJECTIONS:
        return False
    if kind not in REEXAMINABLE_REJECTIONS:
        return False
    return int(rubric_version or 0) < QUALIFICATION_RUBRIC_VERSION
