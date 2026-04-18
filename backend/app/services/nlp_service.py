from __future__ import annotations

import re
from typing import Any

import numpy as np
import spacy

from app.services.embedding_service import embedding_service
from app.services.nlp_model_service import nlp_model_service

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
        self._active_intent_centroids: dict[str, np.ndarray] = {}
        self._active_intent_classifier_labels: list[str] = []
        self._active_intent_classifier_weights: np.ndarray | None = None
        self._active_intent_classifier_bias: np.ndarray | None = None
        self._active_entity_lexicon: dict[str, list[str]] = {}
        self._active_model_id: str | None = None

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

    async def _refresh_active_model(self) -> None:
        active = await nlp_model_service.get_active()
        if active.model_id == self._active_model_id:
            return
        self._active_model_id = active.model_id
        self._active_intent_centroids = dict(active.intent_centroids or {})
        self._active_intent_classifier_labels = list(active.intent_classifier_labels or [])
        self._active_intent_classifier_weights = (
            np.asarray(active.intent_classifier_weights, dtype=np.float32)
            if active.intent_classifier_weights is not None
            else None
        )
        self._active_intent_classifier_bias = (
            np.asarray(active.intent_classifier_bias, dtype=np.float32)
            if active.intent_classifier_bias is not None
            else None
        )
        self._active_entity_lexicon = dict(active.entity_lexicon or {})

    async def classify_intent(self, query: str) -> dict[str, Any]:
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return {
                "intent": "internships",
                "scores": {key: 0.0 for key in self._intent_keys},
                "confidence": 0.0,
            }

        await self._refresh_active_model()
        if (
            self._active_intent_classifier_labels
            and self._active_intent_classifier_weights is not None
            and self._active_intent_classifier_bias is not None
        ):
            query_embedding = await embedding_service.embed_query(cleaned_query)
            weights = self._active_intent_classifier_weights
            bias = self._active_intent_classifier_bias
            if (
                weights.ndim == 2
                and bias.ndim == 1
                and weights.shape[0] == len(self._active_intent_classifier_labels)
                and bias.shape[0] == len(self._active_intent_classifier_labels)
                and weights.shape[1] == query_embedding.shape[0]
            ):
                logits = (weights @ query_embedding.reshape(-1, 1)).reshape(-1) + bias
                logits = logits - np.max(logits)
                probabilities = np.exp(logits)
                denom = float(np.sum(probabilities))
                if denom > 0:
                    probabilities = probabilities / denom
                score_map = {
                    self._active_intent_classifier_labels[idx]: round(float(probabilities[idx]), 4)
                    for idx in range(len(self._active_intent_classifier_labels))
                }
                sorted_labels = sorted(score_map.items(), key=lambda item: item[1], reverse=True)
                top_intent, top_score = sorted_labels[0] if sorted_labels else ("internships", 0.0)
                return {
                    "intent": top_intent,
                    "scores": score_map,
                    "confidence": round(float(top_score), 4),
                    "model_id": self._active_model_id,
                    "model_kind": "linear_head",
                }

        if self._active_intent_centroids:
            query_embedding = await embedding_service.embed_query(cleaned_query)
            scores = {
                label: float(np.dot(query_embedding, centroid))
                for label, centroid in self._active_intent_centroids.items()
                if centroid.shape == query_embedding.shape
            }
            score_map = {
                str(label): round(float(max(-1.0, min(1.0, score))), 4)
                for label, score in scores.items()
            }
            sorted_labels = sorted(score_map.items(), key=lambda item: item[1], reverse=True)
            top_intent, top_score = sorted_labels[0] if sorted_labels else ("internships", 0.0)
            return {
                "intent": top_intent,
                "scores": score_map,
                "confidence": round(float((top_score + 1.0) / 2.0), 4),
                "model_id": self._active_model_id,
                "model_kind": "centroid",
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
            "model_id": self._active_model_id,
            "model_kind": "seed",
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

    async def extract_entities_with_model(self, text: str) -> dict[str, list[str]]:
        await self._refresh_active_model()
        extracted = self.extract_entities(text)
        if not self._active_entity_lexicon:
            return extracted

        haystack = f" {(text or '').lower()} "
        merged: dict[str, list[str]] = {}
        for key, values in extracted.items():
            combined = list(values)
            seen = {item.lower() for item in values}
            for lexeme in self._active_entity_lexicon.get(key, []):
                token = (lexeme or "").strip().lower()
                if not token or token in seen:
                    continue
                if f" {token} " in haystack:
                    combined.append(lexeme)
                    seen.add(token)
            merged[key] = combined
        return merged


nlp_service = NLPService()
