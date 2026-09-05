"""Domain skill vocabularies the learned extractor does not cover.

The skill extractor is trained on mainstream tech and business postings, so it
returns nothing at all for an AYUSH posting. Measured before this existed:

    extract("Ayurveda research associate: Panchakarma, Dravyaguna,
             clinical documentation, patient counselling.")  ->  []

An empty extraction is not a degraded result, it is a silent one. It means an
AYUSH domain produces no demand table, which means a BAMS student is handed
either no questionnaire or the software-engineering one, and the skill gap
feature reports confidently on a corpus it never understood.

This lives in code rather than inside the trained artifact on purpose. The
artifact is a binary produced by a training run, so terms added there vanish at
the next retrain and cannot be reviewed in a diff. A vocabulary is a claim about
what a competency is called, which is exactly the kind of claim that belongs
somewhere a domain expert can read and correct.

Matching is whole-phrase and word-bounded: substring matching turns "yoga" into
a match inside unrelated words, and these terms are shown to students as advice.
"""

from __future__ import annotations

import re
from typing import Iterable

# Ayurveda: clinical procedures and the BAMS/NCISM subject areas. The subject
# names double as competencies here because that is how AYUSH postings ask for
# them - "candidate should have Kayachikitsa background".
AYURVEDA_SKILLS: tuple[str, ...] = (
    "panchakarma",
    "abhyanga",
    "basti",
    "virechana",
    "vamana",
    "nasya",
    "raktamokshana",
    "shirodhara",
    "nadi pariksha",
    "prakriti assessment",
    "shodhana",
    "shamana",
    "kayachikitsa",
    "shalya tantra",
    "shalakya tantra",
    "prasuti tantra",
    "kaumarbhritya",
    "agada tantra",
    "swasthavritta",
    "rachana sharira",
    "kriya sharira",
    "roga nidana",
    "dravyaguna",
    "rasashastra",
    "bhaishajya kalpana",
    "charaka samhita",
    "sushruta samhita",
    "ashtanga hridaya",
    "ayurvedic pharmacy",
    "ayurvedic medicine",
)

YOGA_NATUROPATHY_SKILLS: tuple[str, ...] = (
    "yoga therapy",
    "asana",
    "pranayama",
    "naturopathy",
    "hydrotherapy",
    "meditation",
    "yogic counselling",
    "diet therapy",
)

UNANI_SIDDHA_HOMOEOPATHY_SKILLS: tuple[str, ...] = (
    "unani medicine",
    "ilaj bil tadbeer",
    "hijama",
    "regimenal therapy",
    "siddha medicine",
    "varmam",
    "homoeopathy",
    "materia medica",
    "homoeopathic repertory",
    "case taking",
)

# What actually makes an AYUSH graduate employable outside a clinic: pharma
# manufacturing, regulatory work and research roles.
AYUSH_INDUSTRY_SKILLS: tuple[str, ...] = (
    "pharmacovigilance",
    "clinical research",
    "clinical trials",
    "good manufacturing practice",
    "herbal formulation",
    "phytochemistry",
    "medicinal plants",
    "drug standardisation",
    "drug standardization",
    "quality control",
    "ayurvedic pharmacopoeia",
    "regulatory affairs",
    "medical documentation",
    "patient counselling",
    "patient counseling",
    "clinical documentation",
    "public health",
    "epidemiology",
    "medical writing",
)

AYUSH_VOCABULARY: tuple[str, ...] = (
    AYURVEDA_SKILLS
    + YOGA_NATUROPATHY_SKILLS
    + UNANI_SIDDHA_HOMOEOPATHY_SKILLS
    + AYUSH_INDUSTRY_SKILLS
)

#: Every supplementary vocabulary, keyed for future domains.
DOMAIN_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "ayush": AYUSH_VOCABULARY,
}


def all_vocabulary_terms() -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for terms in DOMAIN_VOCABULARIES.values():
        for term in terms:
            seen.setdefault(term.strip().lower(), None)
    return tuple(seen)


def _compile(terms: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for term in terms:
        cleaned = " ".join(str(term or "").split()).lower()
        if not cleaned:
            continue
        # Whole-phrase, word-bounded. Substring matching would find "basti"
        # inside unrelated words and "asana" inside "hasan", and these strings
        # are shown to a student as a competency they are missing.
        pattern = re.compile(r"\b" + r"\s+".join(re.escape(part) for part in cleaned.split()) + r"\b")
        compiled.append((cleaned, pattern))
    # Longest first so "shalya tantra" wins over a bare "tantra" were one added.
    compiled.sort(key=lambda item: len(item[0]), reverse=True)
    return compiled


_COMPILED = _compile(all_vocabulary_terms())


def vocabulary_skill_tags(text: str) -> list[str]:
    """Terms from the supplementary vocabularies present in the text."""
    lowered = " ".join(str(text or "").split()).lower()
    if not lowered:
        return []
    found: list[str] = []
    for term, pattern in _COMPILED:
        if pattern.search(lowered):
            found.append(term)
    return found
