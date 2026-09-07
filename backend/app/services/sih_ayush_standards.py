"""What the Ayush sector requires of a graduate, from the sector's own documents.

Every other demand figure on this platform is derived from live postings. For
Ayush that is not available, and the honest thing is to say so rather than to
report a thin scrape as though it were a market.

Measured, twice, before writing this. Thirty candidate sources were fetched and
read the way the extractor reads them:

  * the councils and national institutes - Ministry of Ayush, CCRAS, CCRUM,
    CCRYN, NIA, AIIA, ITRA, MDNIY, NMPB - publish vacancies as PDF notices on a
    notice board. Best yield was 7 rows from CCRAS, of which 2 were navigation.
  * the manufacturers and wellness employers - Dabur, Himalaya, Baidyanath,
    Kerala Ayurveda, Charak, Emami, Patanjali, Jiva, AVP - run JavaScript
    careers portals that render nothing a parser can read. Best yield was 3.
  * the national channel, NCS, is a search application: 24 rows of its own
    navigation and no postings.

A demand table built from that would be a statement about which websites
happen to render server-side, dressed up as a statement about the Ayush job
market. This repo has published that shape of number twice before and it is the
thing it is most careful about now.

So the Ayush demand signal comes from a different kind of evidence, and one an
Ayush academic would consider better: the competencies the sector's own
published standards require of each role graduates actually enter. That is what
"skill mapping" means in a regulated profession - a BAMS graduate's readiness is
defined against the NCISM curriculum and the role's occupational standard, not
against how many web pages mentioned a word last week.

Provenance is carried on every row and rendered, so nobody can mistake this for
a scrape. `evidence_basis` says which document a requirement comes from, and
`DEMAND_BASIS` is what the UI prints above the table.

Two things this deliberately does not do. It does not invent a Qualification
Pack code or a document number - a citation nobody can follow is worse than no
citation, and in a regulated field it is the kind of error that ends a
conversation with a domain expert. And it does not assign spurious precision:
weights are ordinal bands, described as such, because "this competency is
required by more of the roles graduates enter" is defensible and "this
competency appears in 4.1% of the market" would not be.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Printed above any table derived from this module. The reader is told what
#: kind of evidence they are looking at, in the same place as the numbers.
DEMAND_BASIS = (
    "Derived from the NCISM undergraduate Ayurveda curriculum and the "
    "competencies required by the roles BAMS graduates enter, not from scraped "
    "job postings. Ayush employers and councils publish vacancies as PDF "
    "notices, so no live posting feed exists for this sector."
)

#: How widely a competency is required across the roles graduates enter.
#: Ordinal, not a percentage of anything - see the module docstring.
CORE = "core"          # required by nearly every role a graduate enters
COMMON = "common"      # required by several
SPECIALIST = "specialist"  # required by one route, and decisive for it

WEIGHTS: dict[str, float] = {CORE: 1.0, COMMON: 0.65, SPECIALIST: 0.35}

BAND_LABELS: dict[str, str] = {
    CORE: "Required across most graduate roles",
    COMMON: "Required in several graduate roles",
    SPECIALIST: "Decisive for one specialisation",
}


@dataclass(frozen=True)
class Competency:
    """One thing a graduate is expected to be able to do."""

    skill: str
    band: str
    #: Which document this requirement is traceable to. Written in words a
    #: reader can act on rather than as a code this module cannot verify.
    evidence_basis: str
    #: The NCISM subject a student would have met it in, where there is one.
    taught_in: str | None = None


@dataclass(frozen=True)
class AyushRole:
    """A role BAMS and allied Ayush graduates actually enter."""

    title: str
    sector: str
    competencies: tuple[str, ...]
    note: str = ""


#: The competency set, keyed by the normalised skill string the rest of the
#: platform uses. Subject names are the NCISM undergraduate Ayurveda subjects;
#: the practice competencies are the ones those subjects exist to produce.
COMPETENCIES: tuple[Competency, ...] = (
    Competency("kayachikitsa", CORE,
               "NCISM BAMS curriculum: general medicine, the largest clinical subject.",
               taught_in="Kayachikitsa"),
    Competency("panchakarma", CORE,
               "NCISM BAMS curriculum, and the defining procedure set of Ayurvedic therapeutics.",
               taught_in="Panchakarma"),
    Competency("nadi pariksha", COMMON,
               "Clinical examination taught under Roga Nidana; the sector's characteristic diagnostic method.",
               taught_in="Roga Nidana"),
    Competency("dravyaguna", CORE,
               "NCISM BAMS curriculum: materia medica and pharmacology of medicinal plants.",
               taught_in="Dravyaguna Vigyana"),
    Competency("rasashastra", COMMON,
               "NCISM BAMS curriculum: mineral and metallic preparations, and the basis of formulation work.",
               taught_in="Rasashastra evam Bhaishajya Kalpana"),
    Competency("swasthavritta", CORE,
               "NCISM BAMS curriculum: preventive medicine, public health and lifestyle.",
               taught_in="Swasthavritta evam Yoga"),
    Competency("yoga therapy", COMMON,
               "Taught within Swasthavritta; the competency behind therapeutic yoga roles.",
               taught_in="Swasthavritta evam Yoga"),
    Competency("shalya tantra", SPECIALIST,
               "NCISM BAMS curriculum: surgery, including ksharasutra practice.",
               taught_in="Shalya Tantra"),
    Competency("shalakya tantra", SPECIALIST,
               "NCISM BAMS curriculum: diseases of the eye, ear, nose and throat.",
               taught_in="Shalakya Tantra"),
    Competency("prasuti tantra", SPECIALIST,
               "NCISM BAMS curriculum: obstetrics and gynaecology.",
               taught_in="Prasuti Tantra evam Stri Roga"),
    Competency("kaumarbhritya", SPECIALIST,
               "NCISM BAMS curriculum: paediatrics.",
               taught_in="Kaumarbhritya"),
    Competency("agada tantra", COMMON,
               "NCISM BAMS curriculum: toxicology and medical jurisprudence.",
               taught_in="Agada Tantra"),
    # Competencies the curriculum does not centre, which industry roles require.
    # These are where the curriculum signal usually finds its widest gaps, and
    # they are the argument this platform exists to make.
    Competency("gmp compliance", COMMON,
               "Required of quality and production roles in licensed Ayurvedic manufacturing.",
               taught_in=None),
    Competency("pharmacovigilance", COMMON,
               "Required by the national pharmacovigilance programme for Ayush products.",
               taught_in=None),
    Competency("clinical research", COMMON,
               "Required of research-assistant and trial-coordination roles at councils and institutes.",
               taught_in=None),
    Competency("raw drug authentication", SPECIALIST,
               "Required of quality-control roles: identifying and grading crude drugs.",
               taught_in="Dravyaguna Vigyana"),
    Competency("medical documentation", COMMON,
               "Required of hospital and insurance-facing roles, and of NABH accreditation work.",
               taught_in=None),
    Competency("patient counselling", CORE,
               "Required of every clinical role, and the competency graduates most often lack on entry.",
               taught_in=None),
)

#: The roles graduates actually enter. Used to explain a gap in terms of the
#: job it closes, which is what makes the signal actionable to a department.
ROLES: tuple[AyushRole, ...] = (
    AyushRole("Ayurveda Medical Officer", "Government and hospital practice",
              ("kayachikitsa", "panchakarma", "nadi pariksha", "swasthavritta",
               "patient counselling", "medical documentation"),
              "The route most BAMS graduates take; state and NHM postings."),
    AyushRole("Panchakarma Physician / Therapist", "Wellness and hospital practice",
              ("panchakarma", "kayachikitsa", "patient counselling", "swasthavritta")),
    AyushRole("Quality Control Officer", "Ayurvedic manufacturing",
              ("rasashastra", "dravyaguna", "gmp compliance", "raw drug authentication")),
    AyushRole("Pharmacovigilance Associate", "Regulatory and industry",
              ("pharmacovigilance", "dravyaguna", "medical documentation", "clinical research")),
    AyushRole("Research Assistant", "Councils and national institutes",
              ("clinical research", "kayachikitsa", "medical documentation", "dravyaguna")),
    AyushRole("Yoga Therapist", "Wellness and preventive care",
              ("yoga therapy", "swasthavritta", "patient counselling")),
    AyushRole("Ksharasutra Specialist", "Surgical practice",
              ("shalya tantra", "kayachikitsa", "patient counselling")),
)


#: The domain string an Ayush demand snapshot is stored under.
AYUSH_DOMAIN = "Ayurveda and Ayush"

#: Field-of-study and specialisation values that mean "this student is in an
#: Ayush discipline".
#:
#: `domain` on a profile is one of five coarse buckets - Management,
#: Engineering, Arts & Science, Medicine, Law - so a BAMS student and an MBBS
#: student both carry "Medicine". Keying the demand table on that alone would
#: hand an Ayurveda cohort a table about allopathic practice, or hand an MBBS
#: cohort Panchakarma. The discipline lives in the more specific field, and that
#: is what has to be read.
AYUSH_FIELD_MARKERS: tuple[str, ...] = (
    "ayurved", "ayush", "bams", "unani", "bums", "siddha", "bsms",
    "homoeopath", "homeopath", "bhms", "naturopath", "bnys", "yoga",
    "panchakarma", "rasashastra", "dravyaguna",
)


def is_ayush_field(*values: str | None) -> bool:
    """Whether any of these profile values names an Ayush discipline.

    Takes several values because the discipline may be recorded as the course
    ("BAMS"), the specialisation ("Ayurveda"), or the field of study, depending
    on which form the student filled in.
    """
    haystack = " ".join(str(value or "").lower() for value in values)
    return any(marker in haystack for marker in AYUSH_FIELD_MARKERS)


def competency_by_skill() -> dict[str, Competency]:
    return {item.skill: item for item in COMPETENCIES}


def demand_rows() -> list[dict[str, object]]:
    """The competency set in the shape the demand table already consumes.

    `share` is the ordinal band's weight, so ranking and the gap arithmetic
    behave exactly as they do for a scraped domain. It is never presented as a
    share of postings: `basis` travels with every row and the UI prints
    DEMAND_BASIS above the table.
    """
    by_skill = competency_by_skill()
    role_counts: dict[str, int] = {}
    for role in ROLES:
        for skill in role.competencies:
            role_counts[skill] = role_counts.get(skill, 0) + 1

    rows: list[dict[str, object]] = []
    for item in COMPETENCIES:
        rows.append(
            {
                "skill": item.skill,
                "share": WEIGHTS.get(item.band, 0.35),
                "band": item.band,
                "band_label": BAND_LABELS.get(item.band, item.band),
                "roles_requiring": role_counts.get(item.skill, 0),
                "evidence_basis": item.evidence_basis,
                "taught_in": item.taught_in,
                "is_soft": item.skill in {"patient counselling", "medical documentation"},
                "basis": "occupational_standard",
            }
        )
    # Widest requirement first, then by how many graduate roles need it - so a
    # department reads the list in the order it would act on.
    rows.sort(key=lambda row: (-float(row["share"]), -int(row["roles_requiring"])))
    return rows


def roles_requiring(skill: str) -> list[str]:
    """Which graduate roles a competency unlocks. Turns a gap into a job."""
    return [role.title for role in ROLES if skill in role.competencies]
