from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import md5
from typing import Any, Optional

import numpy as np

from app.models.nlp_model_version import NLPModelVersion
from app.services.embedding_service import embedding_service

ENTITY_KEYS = ("deadlines", "locations", "companies", "eligibility", "duration")


@dataclass(frozen=True)
class ActiveNLPModel:
    model_id: Optional[str]
    intent_centroids: dict[str, np.ndarray]
    entity_lexicon: dict[str, list[str]]
    metrics: dict[str, float]


_cache: ActiveNLPModel | None = None
_cache_until: datetime | None = None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_entities(payload: dict[str, Any] | None) -> dict[str, list[str]]:
    data = payload or {}
    normalized: dict[str, list[str]] = {}
    for key in ENTITY_KEYS:
        values = data.get(key) or []
        clean_values: list[str] = []
        seen: set[str] = set()
        if isinstance(values, list):
            for value in values:
                text = _normalize_text(value)
                if not text:
                    continue
                lowered = text.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                clean_values.append(text)
        normalized[key] = clean_values
    return normalized


def _hash_bucket(value: str, buckets: int = 10) -> int:
    digest = md5(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % max(1, int(buckets))


def _f1(precision: float, recall: float) -> float:
    if precision <= 0.0 or recall <= 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


class NLPModelService:
    def _to_active(self, model: NLPModelVersion | None) -> ActiveNLPModel:
        if not model:
            return ActiveNLPModel(model_id=None, intent_centroids={}, entity_lexicon={}, metrics={})

        centroids: dict[str, np.ndarray] = {}
        for label, vector in (model.intent_centroids or {}).items():
            array = np.asarray(vector or [], dtype=np.float32)
            if array.size == 0:
                continue
            norm = float(np.linalg.norm(array))
            if norm > 0:
                array = array / norm
            centroids[str(label)] = array

        entity_lexicon: dict[str, list[str]] = {}
        for key in ENTITY_KEYS:
            values = model.entity_lexicon.get(key) or []
            entity_lexicon[key] = [value for value in values if _normalize_text(value)]

        return ActiveNLPModel(
            model_id=str(model.id),
            intent_centroids=centroids,
            entity_lexicon=entity_lexicon,
            metrics={str(k): float(v) for k, v in (model.metrics or {}).items()},
        )

    async def get_active(self, *, cache_ttl_seconds: int = 60) -> ActiveNLPModel:
        global _cache, _cache_until
        now = datetime.utcnow()
        if _cache is not None and _cache_until is not None and now <= _cache_until:
            return _cache

        model = await NLPModelVersion.find_one(NLPModelVersion.is_active == True)  # noqa: E712
        active = self._to_active(model)
        _cache = active
        _cache_until = now + timedelta(seconds=max(0, int(cache_ttl_seconds)))
        return active

    async def deactivate_all(self) -> int:
        rows = await NLPModelVersion.find_many(NLPModelVersion.is_active == True).to_list()  # noqa: E712
        for row in rows:
            row.is_active = False
            row.updated_at = datetime.utcnow()
            await row.save()

        global _cache, _cache_until
        _cache = None
        _cache_until = None
        return len(rows)

    async def activate(self, *, model_id: str) -> NLPModelVersion:
        await self.deactivate_all()
        model = await NLPModelVersion.get(model_id)
        if not model:
            raise ValueError("model_not_found")
        model.is_active = True
        model.updated_at = datetime.utcnow()
        await model.save()

        global _cache, _cache_until
        _cache = None
        _cache_until = None
        return model

    async def _build_intent_centroids(self, rows: list[dict[str, Any]]) -> dict[str, list[float]]:
        by_intent: dict[str, list[str]] = {}
        for row in rows:
            intent = _normalize_text(row.get("intent")).lower()
            text = _normalize_text(row.get("text"))
            if not intent or not text:
                continue
            by_intent.setdefault(intent, []).append(text)

        centroids: dict[str, list[float]] = {}
        for intent, texts in by_intent.items():
            vectors = await embedding_service.embed_texts(texts)
            if vectors.size == 0:
                continue
            centroid = np.asarray(vectors, dtype=np.float32).mean(axis=0)
            norm = float(np.linalg.norm(centroid))
            if norm > 0:
                centroid = centroid / norm
            centroids[intent] = [float(value) for value in centroid.tolist()]
        return centroids

    def _build_entity_lexicon(self, rows: list[dict[str, Any]], *, min_count: int = 1) -> dict[str, list[str]]:
        counter: dict[str, dict[str, int]] = {key: {} for key in ENTITY_KEYS}
        for row in rows:
            entities = _normalize_entities(row.get("entities"))
            for key in ENTITY_KEYS:
                for value in entities.get(key, []):
                    lowered = value.lower()
                    counter[key][lowered] = counter[key].get(lowered, 0) + 1

        lexicon: dict[str, list[str]] = {}
        for key in ENTITY_KEYS:
            pairs = [(value, count) for value, count in counter[key].items() if count >= int(max(1, min_count))]
            pairs.sort(key=lambda item: (-item[1], item[0]))
            lexicon[key] = [value for value, _count in pairs[:200]]
        return lexicon

    async def _predict_intent(self, text: str, centroids: dict[str, np.ndarray]) -> tuple[str, float]:
        if not centroids:
            return "internships", 0.0
        vector = await embedding_service.embed_query(text)
        best_label = ""
        best_score = -2.0
        for label, centroid in centroids.items():
            if centroid.shape != vector.shape:
                continue
            score = float(np.dot(vector, centroid))
            if score > best_score:
                best_score = score
                best_label = label
        confidence = max(0.0, min(1.0, (best_score + 1.0) / 2.0))
        return best_label or "internships", confidence

    def _predict_entities(self, text: str, lexicon: dict[str, list[str]]) -> dict[str, list[str]]:
        haystack = f" {_normalize_text(text).lower()} "
        result: dict[str, list[str]] = {}
        for key in ENTITY_KEYS:
            hits: list[str] = []
            for value in lexicon.get(key, []):
                token = _normalize_text(value).lower()
                if not token:
                    continue
                if f" {token} " in haystack:
                    hits.append(value)
                if len(hits) >= 10:
                    break
            result[key] = hits
        return result

    async def train_and_register(
        self,
        *,
        examples: list[dict[str, Any]],
        name: str = "nlp-model-v1",
        notes: Optional[str] = None,
        auto_activate: bool = True,
        min_intent_macro_f1_for_activation: float = 0.55,
    ) -> NLPModelVersion:
        cleaned = []
        for row in examples:
            text = _normalize_text(row.get("text"))
            intent = _normalize_text(row.get("intent")).lower()
            if not text or not intent:
                continue
            cleaned.append(
                {
                    "text": text,
                    "intent": intent,
                    "entities": _normalize_entities(row.get("entities")),
                }
            )
        if len(cleaned) < 20:
            raise ValueError("insufficient_training_data")

        train_rows: list[dict[str, Any]] = []
        test_rows: list[dict[str, Any]] = []
        for row in cleaned:
            bucket = _hash_bucket(f"{row['intent']}::{row['text']}", buckets=10)
            if bucket < 8:
                train_rows.append(row)
            else:
                test_rows.append(row)
        if len(test_rows) < 5:
            test_rows = cleaned[-max(5, len(cleaned) // 5) :]
            train_rows = cleaned[: max(1, len(cleaned) - len(test_rows))]

        centroid_payload = await self._build_intent_centroids(train_rows)
        centroids = {
            key: np.asarray(values, dtype=np.float32)
            for key, values in centroid_payload.items()
            if values
        }
        lexicon = self._build_entity_lexicon(train_rows, min_count=1)

        confusion: dict[str, dict[str, int]] = {}
        intent_labels = sorted({row["intent"] for row in cleaned})
        for true_label in intent_labels:
            confusion[true_label] = {pred_label: 0 for pred_label in intent_labels}

        correct = 0
        entity_tp = 0
        entity_fp = 0
        entity_fn = 0

        for row in test_rows:
            predicted_intent, _confidence = await self._predict_intent(row["text"], centroids)
            true_label = row["intent"]
            if true_label not in confusion:
                confusion[true_label] = {}
            confusion[true_label][predicted_intent] = confusion[true_label].get(predicted_intent, 0) + 1
            if predicted_intent == true_label:
                correct += 1

            predicted_entities = self._predict_entities(row["text"], lexicon)
            true_entities = row["entities"]
            for key in ENTITY_KEYS:
                pred_set = {value.lower() for value in predicted_entities.get(key, [])}
                true_set = {value.lower() for value in true_entities.get(key, [])}
                entity_tp += len(pred_set.intersection(true_set))
                entity_fp += len(pred_set - true_set)
                entity_fn += len(true_set - pred_set)

        intent_accuracy = float(correct / max(1, len(test_rows)))
        per_label_f1: list[float] = []
        for label in intent_labels:
            tp = int(confusion.get(label, {}).get(label, 0))
            fp = sum(int(confusion.get(other, {}).get(label, 0)) for other in intent_labels if other != label)
            fn = sum(int(confusion.get(label, {}).get(other, 0)) for other in intent_labels if other != label)
            precision = float(tp / max(1, tp + fp))
            recall = float(tp / max(1, tp + fn))
            per_label_f1.append(_f1(precision, recall))
        intent_macro_f1 = float(sum(per_label_f1) / max(1, len(per_label_f1)))

        entity_precision = float(entity_tp / max(1, entity_tp + entity_fp))
        entity_recall = float(entity_tp / max(1, entity_tp + entity_fn))
        entity_micro_f1 = _f1(entity_precision, entity_recall)

        model = NLPModelVersion(
            name=_normalize_text(name) or "nlp-model-v1",
            is_active=False,
            intent_labels=intent_labels,
            intent_centroids=centroid_payload,
            entity_lexicon=lexicon,
            metrics={
                "intent_accuracy": round(intent_accuracy, 6),
                "intent_macro_f1": round(intent_macro_f1, 6),
                "entity_precision": round(entity_precision, 6),
                "entity_recall": round(entity_recall, 6),
                "entity_micro_f1": round(entity_micro_f1, 6),
            },
            confusion_matrix=confusion,
            training_rows=len(cleaned),
            split_summary={
                "train_rows": len(train_rows),
                "test_rows": len(test_rows),
            },
            metadata={
                "feature": "intent_centroids+entity_lexicon",
                "embedding_provider": embedding_service.provider,
            },
            notes=notes,
            updated_at=datetime.utcnow(),
        )
        await model.insert()

        if auto_activate and intent_macro_f1 >= float(min_intent_macro_f1_for_activation):
            await self.activate(model_id=str(model.id))
            refreshed = await NLPModelVersion.get(model.id)
            if refreshed:
                model = refreshed

        return model


nlp_model_service = NLPModelService()
