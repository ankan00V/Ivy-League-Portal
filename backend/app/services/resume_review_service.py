from __future__ import annotations

import re
from typing import Any


REVIEW_VERSION = "resume_readiness.v1"
MAX_REVIEW_TEXT_CHARS = 24_000
SECTION_PATTERNS = {
    "summary": re.compile(r"\b(summary|professional profile|objective|about me)\b", re.IGNORECASE),
    "education": re.compile(r"\beducation\b", re.IGNORECASE),
    "skills": re.compile(r"\b(skills|technical skills|technologies)\b", re.IGNORECASE),
    "experience": re.compile(r"\b(work experience|professional experience|employment|internship experience|experience)\b", re.IGNORECASE),
    "projects": re.compile(r"\b(projects|personal projects|academic projects)\b", re.IGNORECASE),
}
ACTION_VERBS = {
    "accelerated",
    "achieved",
    "automated",
    "built",
    "created",
    "delivered",
    "designed",
    "developed",
    "improved",
    "implemented",
    "increased",
    "launched",
    "led",
    "optimized",
    "reduced",
    "shipped",
}
SKILL_TERMS = {
    "aws",
    "azure",
    "c++",
    "css",
    "data analysis",
    "docker",
    "fastapi",
    "flask",
    "git",
    "html",
    "java",
    "javascript",
    "kubernetes",
    "machine learning",
    "mongodb",
    "next.js",
    "node.js",
    "pandas",
    "postgresql",
    "python",
    "pytorch",
    "react",
    "scikit-learn",
    "sql",
    "tensorflow",
    "typescript",
}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(str(value).split()).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _category(
    *,
    key: str,
    label: str,
    score: int,
    maximum: int,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": max(0, min(int(score), maximum)),
        "maximum": maximum,
        "evidence": _dedupe(evidence),
    }


def _profile_terms(value: str) -> set[str]:
    return {
        term.strip().lower()
        for term in re.split(r"[,|/\n]", str(value or ""))
        if len(term.strip()) >= 2
    }


def review_resume(
    text: str,
    *,
    profile_skills: str = "",
    preferred_roles: str = "",
) -> dict[str, Any]:
    normalized = " ".join(str(text or "").replace("\x00", " ").split())[:MAX_REVIEW_TEXT_CHARS]
    if len(normalized) < 40:
        raise ValueError("Resume text is too short to review. Upload a text-readable PDF, DOCX, or TXT file.")

    lowered = normalized.lower()
    sections = {name for name, pattern in SECTION_PATTERNS.items() if pattern.search(normalized)}
    email_present = bool(re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", normalized))
    phone_present = bool(re.search(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)", normalized))
    link_present = bool(re.search(r"(?:https?://|www\.|linkedin\.com|github\.com)", lowered))

    contact_score = (4 if email_present else 0) + (3 if phone_present else 0) + (3 if link_present else 0)
    contact_evidence = [
        *( ["Email address found"] if email_present else ["Add a professional email address"] ),
        *( ["Phone number found"] if phone_present else ["Add a phone number"] ),
        *( ["Professional or portfolio link found"] if link_present else ["Add LinkedIn, GitHub, or portfolio link"] ),
    ]

    structure_score = min(20, len(sections) * 4)
    missing_sections = [name.title() for name in SECTION_PATTERNS if name not in sections]
    structure_evidence = [f"{name.title()} section found" for name in sorted(sections)]
    if missing_sections:
        structure_evidence.append(f"Missing labeled sections: {', '.join(missing_sections)}")

    observed_skills = {term for term in SKILL_TERMS if term in lowered}
    profile_skill_terms = _profile_terms(profile_skills)
    profile_skill_matches = {term for term in profile_skill_terms if term in lowered}
    skills_section_present = "skills" in sections
    skills_score = min(20, (8 if skills_section_present else 0) + min(8, len(observed_skills) * 2) + min(4, len(profile_skill_matches)))
    skill_evidence: list[str] = []
    if skills_section_present:
        skill_evidence.append("Dedicated skills section found")
    if observed_skills:
        skill_evidence.append(f"Detected technical skills: {', '.join(sorted(observed_skills)[:6])}")
    if profile_skill_terms and not profile_skill_matches:
        skill_evidence.append("Profile skills are not clearly reflected in the resume")
    if not skill_evidence:
        skill_evidence.append("Add a focused technical skills section with relevant tools")

    quantified_results = re.findall(r"(?<!\w)\d+(?:\.\d+)?\s*(?:%|x\b|k\+?|users?\b|customers?\b|hours?\b|days?\b)", lowered)
    action_verb_count = sum(len(re.findall(rf"\b{re.escape(verb)}\b", lowered)) for verb in ACTION_VERBS)
    impact_score = min(20, min(12, len(quantified_results) * 3) + min(8, action_verb_count))
    impact_evidence = []
    if quantified_results:
        impact_evidence.append(f"Quantified outcomes found: {len(quantified_results)}")
    if action_verb_count:
        impact_evidence.append(f"Action-oriented bullets found: {action_verb_count}")
    if not impact_evidence:
        impact_evidence.append("Add outcome-focused bullets with metrics, scale, or time saved")

    project_link_count = len(re.findall(r"(?:github\.com|gitlab\.com|bitbucket\.org|https?://)", lowered))
    experience_score = min(
        20,
        (8 if "experience" in sections else 0)
        + (8 if "projects" in sections else 0)
        + min(4, project_link_count),
    )
    experience_evidence = []
    if "experience" in sections:
        experience_evidence.append("Experience or internship section found")
    if "projects" in sections:
        experience_evidence.append("Projects section found")
    if project_link_count:
        experience_evidence.append("Portfolio or project link found")
    if not experience_evidence:
        experience_evidence.append("Show relevant projects, internships, coursework, or leadership work")

    bullet_count = len(re.findall(r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s+", str(text or "")))
    readable_length = 250 <= len(normalized) <= 8_000
    readability_score = (5 if readable_length else 0) + (3 if bullet_count >= 3 else 0) + (2 if "|" not in normalized[:3_000] else 0)
    readability_evidence = []
    if readable_length:
        readability_evidence.append("Readable text length")
    else:
        readability_evidence.append("Keep the resume concise but substantive (roughly one to two pages)")
    if bullet_count >= 3:
        readability_evidence.append("Bullet-based content found")
    else:
        readability_evidence.append("Use concise bullets instead of dense paragraphs")

    categories = [
        _category(key="contact", label="Contact and links", score=contact_score, maximum=10, evidence=contact_evidence),
        _category(key="structure", label="Resume structure", score=structure_score, maximum=20, evidence=structure_evidence),
        _category(key="skills", label="Skills evidence", score=skills_score, maximum=20, evidence=skill_evidence),
        _category(key="impact", label="Measured impact", score=impact_score, maximum=20, evidence=impact_evidence),
        _category(key="experience", label="Projects and experience", score=experience_score, maximum=20, evidence=experience_evidence),
        _category(key="readability", label="ATS readability", score=readability_score, maximum=10, evidence=readability_evidence),
    ]
    score = sum(category["score"] for category in categories)
    strengths = [category["label"] for category in categories if category["score"] >= category["maximum"] * 0.7]
    weak_categories = [category for category in categories if category["score"] < category["maximum"] * 0.6]
    weaknesses = [category["label"] for category in weak_categories]
    recommendations = [category["evidence"][-1] for category in weak_categories if category["evidence"]]

    role_terms = _profile_terms(preferred_roles)
    role_matches = [term for term in sorted(role_terms) if term in lowered]
    if role_terms and not role_matches:
        recommendations.insert(0, "Tailor the summary and project bullets to the roles selected in your profile.")
    elif role_matches:
        strengths.append("Selected role terms appear in the resume")

    return {
        "version": REVIEW_VERSION,
        "score": score,
        "summary": (
            "Strong resume readiness signals are present. Prioritize the remaining low-scoring categories before applying."
            if score >= 75
            else "This is an advisory readiness score. Strengthen the highlighted areas to make your experience easier to scan."
        ),
        "categories": categories,
        "strengths": _dedupe(strengths)[:5],
        "weaknesses": _dedupe(weaknesses)[:5],
        "recommendations": _dedupe(recommendations)[:5],
        "advisory": "This review measures clarity and ATS readability only. It does not predict hiring outcomes or make eligibility decisions.",
    }
