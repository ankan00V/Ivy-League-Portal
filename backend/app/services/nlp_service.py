from __future__ import annotations

import re
from typing import Any

import numpy as np
import spacy

from app.services.embedding_service import embedding_service

ELIGIBILITY_PATTERN = re.compile(
    r"(?i)(eligible|eligibility|minimum|required|must have|cgpa|gpa|age limit|undergraduate|graduate|final year|experience)"
)
DURATION_PATTERN = re.compile(r"(?i)(\d+\s*(?:day|week|month|year)s?)")

INTENT_LABELS = {
    "internships": "internship roles, summer internships, and trainee positions",
    "research": "research assistantships, fellowships, and lab opportunities",
    "scholarships": "scholarships, grants, and tuition funding programs",
    "hackathons": "hackathons, coding competitions, and innovation challenges",
}


class NLPService:
    def __init__(self) -> None:
        self._nlp = None
        self._intent_embeddings: np.ndarray | None = None
        self._intent_keys = list(INTENT_LABELS.keys())

    def _ensure_nlp(self):
        if self._nlp is not None:
            return self._nlp

        try:
            self._nlp = spacy.load("en_core_web_sm")
        except Exception:
            # Keep the service alive even when model isn't preinstalled.
            self._nlp = spacy.blank("en")
        return self._nlp

    async def _ensure_intent_embeddings(self) -> None:
        if self._intent_embeddings is not None:
            return
        self._intent_embeddings = await embedding_service.embed_texts(INTENT_LABELS.values())

    async def classify_intent(self, query: str) -> dict[str, Any]:
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return {
                "intent": "internships",
                "scores": {key: 0.0 for key in self._intent_keys},
                "confidence": 0.0,
            }

        await self._ensure_intent_embeddings()
        query_embedding = await embedding_service.embed_query(cleaned_query)
        scores = np.dot(self._intent_embeddings, query_embedding).tolist() if self._intent_embeddings is not None else []

        score_map = {
            self._intent_keys[idx]: round(float(max(-1.0, min(1.0, score))), 4)
            for idx, score in enumerate(scores)
        }
        sorted_labels = sorted(score_map.items(), key=lambda item: item[1], reverse=True)
        top_intent, top_score = sorted_labels[0] if sorted_labels else ("internships", 0.0)

        return {
            "intent": top_intent,
            "scores": score_map,
            "confidence": round(float((top_score + 1.0) / 2.0), 4),
        }

    def extract_entities(self, text: str) -> dict[str, list[str]]:
        clean_text = (text or "").strip()
        if not clean_text:
            return {
                "deadlines": [],
                "locations": [],
                "companies": [],
                "eligibility": [],
                "duration": [],
            }

        nlp = self._ensure_nlp()
        doc = nlp(clean_text)

        deadlines: list[str] = []
        locations: list[str] = []
        companies: list[str] = []

        for ent in getattr(doc, "ents", []):
            if ent.label_ in {"DATE", "TIME"}:
                deadlines.append(ent.text.strip())
            elif ent.label_ in {"GPE", "LOC", "FAC"}:
                locations.append(ent.text.strip())
            elif ent.label_ in {"ORG"}:
                companies.append(ent.text.strip())

        duration = [match.group(1).strip() for match in DURATION_PATTERN.finditer(clean_text)]

        eligibility: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", clean_text):
            if ELIGIBILITY_PATTERN.search(sentence):
                eligibility.append(sentence.strip())

        def _dedupe(values: list[str]) -> list[str]:
            output: list[str] = []
            seen: set[str] = set()
            for value in values:
                key = value.lower()
                if not value or key in seen:
                    continue
                seen.add(key)
                output.append(value)
            return output

        return {
            "deadlines": _dedupe(deadlines),
            "locations": _dedupe(locations),
            "companies": _dedupe(companies),
            "eligibility": _dedupe(eligibility)[:5],
            "duration": _dedupe(duration),
        }


nlp_service = NLPService()
