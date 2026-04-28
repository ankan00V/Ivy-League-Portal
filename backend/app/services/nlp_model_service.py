from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import md5
from typing import Any, Optional

import numpy as np

from app.models.nlp_model_version import NLPModelVersion
from app.services.embedding_service import embedding_service
from app.core.time import utc_now

ENTITY_KEYS = ("deadlines", "locations", "companies", "eligibility", "duration")


@dataclass(frozen=True)
class ActiveNLPModel:
    model_id: Optional[str]
    intent_centroids: dict[str, np.ndarray]
    intent_classifier_labels: list[str]
    intent_classifier_weights: np.ndarray | None
    intent_classifier_bias: np.ndarray | None
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


def _softmax(logits: np.ndarray) -> np.ndarray:
    if logits.ndim == 1:
        logits = logits.reshape(1, -1)
    stable = logits - np.max(logits, axis=1, keepdims=True)
    exp_values = np.exp(stable)
    denom = np.sum(exp_values, axis=1, keepdims=True)
    denom = np.clip(denom, 1e-12, None)
    return exp_values / denom


def _empty_confusion(labels: list[str]) -> dict[str, dict[str, int]]:
    return {label: {pred: 0 for pred in labels} for label in labels}


def _macro_f1_from_confusion(confusion: dict[str, dict[str, int]], labels: list[str]) -> float:
    per_label_f1: list[float] = []
    for label in labels:
        tp = int(confusion.get(label, {}).get(label, 0))
        fp = sum(int(confusion.get(other, {}).get(label, 0)) for other in labels if other != label)
        fn = sum(int(confusion.get(label, {}).get(other, 0)) for other in labels if other != label)
        precision = float(tp / max(1, tp + fp))
        recall = float(tp / max(1, tp + fn))
        per_label_f1.append(_f1(precision, recall))
    return float(sum(per_label_f1) / max(1, len(per_label_f1)))


class NLPModelService:
    def _to_active(self, model: NLPModelVersion | None) -> ActiveNLPModel:
        if not model:
            return ActiveNLPModel(
                model_id=None,
                intent_centroids={},
                intent_classifier_labels=[],
                intent_classifier_weights=None,
                intent_classifier_bias=None,
                entity_lexicon={},
                metrics={},
            )

        centroids: dict[str, np.ndarray] = {}
        for label, vector in (model.intent_centroids or {}).items():
            array = np.asarray(vector or [], dtype=np.float32)
            if array.size == 0:
                continue
            norm = float(np.linalg.norm(array))
            if norm > 0:
                array = array / norm
            centroids[str(label)] = array

        classifier_labels: list[str] = []
        classifier_weights: np.ndarray | None = None
        classifier_bias: np.ndarray | None = None
        head = dict(model.intent_classifier_head or {})
        raw_labels = head.get("labels") or []
        raw_weights = head.get("weights") or []
        raw_bias = head.get("bias") or []
        if isinstance(raw_labels, list) and isinstance(raw_weights, list) and isinstance(raw_bias, list):
            labels = [str(label).strip().lower() for label in raw_labels if str(label).strip()]
            weights = np.asarray(raw_weights, dtype=np.float32)
            bias = np.asarray(raw_bias, dtype=np.float32)
            if labels and weights.ndim == 2 and bias.ndim == 1 and weights.shape[0] == len(labels) and bias.shape[0] == len(labels):
                classifier_labels = labels
                classifier_weights = weights
                classifier_bias = bias

        entity_lexicon: dict[str, list[str]] = {}
        for key in ENTITY_KEYS:
            values = model.entity_lexicon.get(key) or []
            entity_lexicon[key] = [value for value in values if _normalize_text(value)]

        return ActiveNLPModel(
            model_id=str(model.id),
            intent_centroids=centroids,
            intent_classifier_labels=classifier_labels,
            intent_classifier_weights=classifier_weights,
            intent_classifier_bias=classifier_bias,
            entity_lexicon=entity_lexicon,
            metrics={str(k): float(v) for k, v in (model.metrics or {}).items()},
        )

    async def get_active(self, *, cache_ttl_seconds: int = 60) -> ActiveNLPModel:
        global _cache, _cache_until
        now = utc_now()
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
            row.updated_at = utc_now()
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
        model.updated_at = utc_now()
        await model.save()

        global _cache, _cache_until
        _cache = None
        _cache_until = None
        return model

    async def _build_intent_centroids(
        self,
        rows: list[dict[str, Any]],
        *,
        vectors: np.ndarray | None = None,
    ) -> dict[str, list[float]]:
        centroids: dict[str, np.ndarray] = {}
        counts: dict[str, int] = {}

        if vectors is not None and vectors.size and len(rows) == int(vectors.shape[0]):
            for idx, row in enumerate(rows):
                label = _normalize_text(row.get("intent")).lower()
                if not label:
                    continue
                vector = np.asarray(vectors[idx], dtype=np.float32)
                if vector.size == 0:
                    continue
                if label not in centroids:
                    centroids[label] = np.zeros_like(vector)
                    counts[label] = 0
                centroids[label] += vector
                counts[label] += 1
        else:
            by_intent: dict[str, list[str]] = {}
            for row in rows:
                intent = _normalize_text(row.get("intent")).lower()
                text = _normalize_text(row.get("text"))
                if not intent or not text:
                    continue
                by_intent.setdefault(intent, []).append(text)

            for intent, texts in by_intent.items():
                intent_vectors = await embedding_service.embed_texts(texts)
                if intent_vectors.size == 0:
                    continue
                centroids[intent] = np.asarray(intent_vectors, dtype=np.float32).mean(axis=0)
                counts[intent] = len(texts)

        payload: dict[str, list[float]] = {}
        for label, vector in centroids.items():
            count = max(1, int(counts.get(label, 1)))
            centroid = vector / float(count)
            norm = float(np.linalg.norm(centroid))
            if norm > 0:
                centroid = centroid / norm
            payload[label] = [float(value) for value in centroid.tolist()]
        return payload

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

    def _predict_intent_from_centroids(
        self,
        vector: np.ndarray,
        centroids: dict[str, np.ndarray],
        *,
        default_label: str,
    ) -> tuple[str, float]:
        if not centroids:
            return default_label, 0.0
        best_label = default_label
        best_score = -2.0
        for label, centroid in centroids.items():
            if centroid.shape != vector.shape:
                continue
            score = float(np.dot(vector, centroid))
            if score > best_score:
                best_score = score
                best_label = label
        confidence = max(0.0, min(1.0, (best_score + 1.0) / 2.0))
        return best_label, confidence

    def _predict_intent_from_linear_head(
        self,
        vector: np.ndarray,
        *,
        labels: list[str],
        weights: np.ndarray,
        bias: np.ndarray,
        default_label: str,
    ) -> tuple[str, float]:
        if not labels or weights.ndim != 2 or bias.ndim != 1:
            return default_label, 0.0
        if weights.shape[0] != len(labels) or bias.shape[0] != len(labels):
            return default_label, 0.0
        if weights.shape[1] != int(vector.size):
            return default_label, 0.0

        logits = (weights @ vector.reshape(-1, 1)).reshape(-1) + bias
        probs = _softmax(logits.reshape(1, -1))[0]
        top_idx = int(np.argmax(probs))
        return labels[top_idx], float(max(0.0, min(1.0, probs[top_idx])))

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

    def _train_linear_head(
        self,
        *,
        vectors: np.ndarray,
        labels_idx: np.ndarray,
        classes: int,
        learning_rate: float,
        epochs: int,
        l2: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        if vectors.size == 0 or labels_idx.size == 0 or int(vectors.shape[0]) != int(labels_idx.shape[0]):
            raise ValueError("invalid_training_vectors")
        if classes <= 1:
            raise ValueError("insufficient_classes")

        n_rows, dim = int(vectors.shape[0]), int(vectors.shape[1])
        weights = np.zeros((classes, dim), dtype=np.float64)
        bias = np.zeros((classes,), dtype=np.float64)

        safe_lr = float(max(1e-4, min(1.0, learning_rate)))
        safe_epochs = int(max(20, min(2000, epochs)))
        safe_l2 = float(max(0.0, min(1.0, l2)))
        batch_size = max(8, min(64, n_rows))

        rng = np.random.default_rng(42)
        for _epoch in range(safe_epochs):
            shuffled = rng.permutation(n_rows)
            for start in range(0, n_rows, batch_size):
                end = min(start + batch_size, n_rows)
                idx = shuffled[start:end]
                xb = vectors[idx].astype(np.float64, copy=False)
                yb = labels_idx[idx]
                logits = xb @ weights.T + bias
                probs = _softmax(logits)

                truth = np.zeros_like(probs)
                truth[np.arange(int(yb.size)), yb] = 1.0
                grad_logits = (probs - truth) / float(max(1, yb.size))
                grad_weights = grad_logits.T @ xb + (safe_l2 * weights)
                grad_bias = grad_logits.sum(axis=0)

                weights -= safe_lr * grad_weights
                bias -= safe_lr * grad_bias

        return weights.astype(np.float32), bias.astype(np.float32)

    def _evaluate_entities(
        self,
        *,
        rows: list[dict[str, Any]],
        lexicon: dict[str, list[str]],
    ) -> dict[str, Any]:
        if not rows:
            return {
                "precision": 0.0,
                "recall": 0.0,
                "micro_f1": 0.0,
                "macro_f1": 0.0,
                "per_key_f1": {key: 0.0 for key in ENTITY_KEYS},
                "rows": 0,
            }

        entity_tp = 0
        entity_fp = 0
        entity_fn = 0
        per_key_counts: dict[str, dict[str, int]] = {key: {"tp": 0, "fp": 0, "fn": 0} for key in ENTITY_KEYS}

        for row in rows:
            predicted_entities = self._predict_entities(row["text"], lexicon)
            true_entities = row["entities"]
            for key in ENTITY_KEYS:
                pred_set = {value.lower() for value in predicted_entities.get(key, [])}
                true_set = {value.lower() for value in true_entities.get(key, [])}
                tp = len(pred_set.intersection(true_set))
                fp = len(pred_set - true_set)
                fn = len(true_set - pred_set)
                entity_tp += tp
                entity_fp += fp
                entity_fn += fn
                per_key_counts[key]["tp"] += tp
                per_key_counts[key]["fp"] += fp
                per_key_counts[key]["fn"] += fn

        entity_precision = float(entity_tp / max(1, entity_tp + entity_fp))
        entity_recall = float(entity_tp / max(1, entity_tp + entity_fn))
        entity_micro_f1 = _f1(entity_precision, entity_recall)

        per_key_f1: dict[str, float] = {}
        for key in ENTITY_KEYS:
            tp = int(per_key_counts[key]["tp"])
            fp = int(per_key_counts[key]["fp"])
            fn = int(per_key_counts[key]["fn"])
            precision = float(tp / max(1, tp + fp))
            recall = float(tp / max(1, tp + fn))
            per_key_f1[key] = _f1(precision, recall)

        entity_macro_f1 = float(sum(per_key_f1.values()) / max(1, len(per_key_f1)))
        return {
            "precision": entity_precision,
            "recall": entity_recall,
            "micro_f1": entity_micro_f1,
            "macro_f1": entity_macro_f1,
            "per_key_f1": per_key_f1,
            "rows": len(rows),
        }

    async def train_and_register(
        self,
        *,
        examples: list[dict[str, Any]],
        name: str = "nlp-model-v1",
        notes: Optional[str] = None,
        auto_activate: bool = True,
        min_intent_macro_f1_for_activation: float = 0.55,
        min_intent_macro_f1_uplift_for_activation: float = 0.0,
        ner_eval_examples: Optional[list[dict[str, Any]]] = None,
        linear_head_learning_rate: float = 0.08,
        linear_head_epochs: int = 220,
        linear_head_l2: float = 1e-4,
    ) -> NLPModelVersion:
        cleaned: list[dict[str, Any]] = []
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

        all_labels = sorted({row["intent"] for row in cleaned})
        train_labels = {row["intent"] for row in train_rows}
        if len(train_labels) < len(all_labels):
            recovered_test_rows: list[dict[str, Any]] = []
            for row in test_rows:
                label = row["intent"]
                if label not in train_labels:
                    train_rows.append(row)
                    train_labels.add(label)
                else:
                    recovered_test_rows.append(row)
            test_rows = recovered_test_rows
        if len(test_rows) < 5:
            test_rows = train_rows[-max(5, len(train_rows) // 5) :]
            train_rows = train_rows[: max(1, len(train_rows) - len(test_rows))]

        train_texts = [row["text"] for row in train_rows]
        test_texts = [row["text"] for row in test_rows]
        train_vectors = await embedding_service.embed_texts(train_texts)
        test_vectors = await embedding_service.embed_texts(test_texts)

        centroid_payload = await self._build_intent_centroids(train_rows, vectors=train_vectors)
        centroids = {key: np.asarray(values, dtype=np.float32) for key, values in centroid_payload.items() if values}
        lexicon = self._build_entity_lexicon(train_rows, min_count=1)

        intent_labels = sorted({row["intent"] for row in cleaned})
        label_to_idx = {label: idx for idx, label in enumerate(intent_labels)}
        train_indices = np.asarray([label_to_idx[row["intent"]] for row in train_rows], dtype=np.int64)
        linear_weights, linear_bias = self._train_linear_head(
            vectors=np.asarray(train_vectors, dtype=np.float32),
            labels_idx=train_indices,
            classes=len(intent_labels),
            learning_rate=linear_head_learning_rate,
            epochs=linear_head_epochs,
            l2=linear_head_l2,
        )

        confusion_baseline = _empty_confusion(intent_labels)
        confusion_ml = _empty_confusion(intent_labels)
        baseline_correct = 0
        ml_correct = 0
        default_label = intent_labels[0] if intent_labels else "internships"

        for idx, row in enumerate(test_rows):
            vector = np.asarray(test_vectors[idx], dtype=np.float32)
            true_label = row["intent"]

            baseline_label, _baseline_conf = self._predict_intent_from_centroids(
                vector,
                centroids,
                default_label=default_label,
            )
            ml_label, _ml_conf = self._predict_intent_from_linear_head(
                vector,
                labels=intent_labels,
                weights=linear_weights,
                bias=linear_bias,
                default_label=baseline_label or default_label,
            )

            confusion_baseline.setdefault(true_label, {}).setdefault(baseline_label, 0)
            confusion_ml.setdefault(true_label, {}).setdefault(ml_label, 0)
            confusion_baseline[true_label][baseline_label] += 1
            confusion_ml[true_label][ml_label] += 1

            if baseline_label == true_label:
                baseline_correct += 1
            if ml_label == true_label:
                ml_correct += 1

        baseline_accuracy = float(baseline_correct / max(1, len(test_rows)))
        ml_accuracy = float(ml_correct / max(1, len(test_rows)))
        baseline_macro_f1 = _macro_f1_from_confusion(confusion_baseline, intent_labels)
        ml_macro_f1 = _macro_f1_from_confusion(confusion_ml, intent_labels)

        ner_eval_rows: list[dict[str, Any]]
        if ner_eval_examples:
            normalized_eval_rows: list[dict[str, Any]] = []
            for row in ner_eval_examples:
                text = _normalize_text(row.get("text"))
                intent = _normalize_text(row.get("intent")).lower() or default_label
                if not text:
                    continue
                normalized_eval_rows.append(
                    {
                        "text": text,
                        "intent": intent,
                        "entities": _normalize_entities(row.get("entities")),
                    }
                )
            ner_eval_rows = normalized_eval_rows or test_rows
        else:
            ner_eval_rows = test_rows

        entity_metrics = self._evaluate_entities(rows=ner_eval_rows, lexicon=lexicon)

        macro_f1_uplift = ml_macro_f1 - baseline_macro_f1
        accuracy_uplift = ml_accuracy - baseline_accuracy

        model = NLPModelVersion(
            name=_normalize_text(name) or "nlp-model-v1",
            is_active=False,
            intent_labels=intent_labels,
            intent_centroids=centroid_payload,
            intent_classifier_head={
                "labels": intent_labels,
                "weights": [[float(value) for value in row] for row in linear_weights.tolist()],
                "bias": [float(value) for value in linear_bias.tolist()],
                "learning_rate": float(max(1e-4, min(1.0, linear_head_learning_rate))),
                "epochs": int(max(20, min(2000, linear_head_epochs))),
                "l2": float(max(0.0, min(1.0, linear_head_l2))),
            },
            entity_lexicon=lexicon,
            metrics={
                "intent_accuracy": round(ml_accuracy, 6),
                "intent_macro_f1": round(ml_macro_f1, 6),
                "intent_accuracy_baseline": round(baseline_accuracy, 6),
                "intent_accuracy_ml": round(ml_accuracy, 6),
                "intent_accuracy_uplift": round(accuracy_uplift, 6),
                "intent_macro_f1_baseline": round(baseline_macro_f1, 6),
                "intent_macro_f1_ml": round(ml_macro_f1, 6),
                "intent_macro_f1_uplift": round(macro_f1_uplift, 6),
                "entity_precision": round(float(entity_metrics["precision"]), 6),
                "entity_recall": round(float(entity_metrics["recall"]), 6),
                "entity_micro_f1": round(float(entity_metrics["micro_f1"]), 6),
                "entity_macro_f1": round(float(entity_metrics["macro_f1"]), 6),
            },
            confusion_matrix=confusion_ml,
            baseline_confusion_matrix=confusion_baseline,
            evaluation_snapshot={
                "intent": {
                    "baseline": {
                        "accuracy": round(baseline_accuracy, 6),
                        "macro_f1": round(baseline_macro_f1, 6),
                        "confusion_matrix": confusion_baseline,
                    },
                    "ml": {
                        "accuracy": round(ml_accuracy, 6),
                        "macro_f1": round(ml_macro_f1, 6),
                        "confusion_matrix": confusion_ml,
                    },
                    "uplift": {
                        "accuracy": round(accuracy_uplift, 6),
                        "macro_f1": round(macro_f1_uplift, 6),
                    },
                    "test_rows": len(test_rows),
                },
                "ner": {
                    "eval_rows": int(entity_metrics["rows"]),
                    "used_dedicated_eval_set": bool(ner_eval_examples),
                    "precision": round(float(entity_metrics["precision"]), 6),
                    "recall": round(float(entity_metrics["recall"]), 6),
                    "micro_f1": round(float(entity_metrics["micro_f1"]), 6),
                    "macro_f1": round(float(entity_metrics["macro_f1"]), 6),
                    "per_key_f1": {
                        key: round(float(value), 6)
                        for key, value in (entity_metrics.get("per_key_f1") or {}).items()
                    },
                },
            },
            training_rows=len(cleaned),
            split_summary={
                "train_rows": len(train_rows),
                "test_rows": len(test_rows),
            },
            metadata={
                "feature": "MiniLM_embeddings+linear_head+entity_lexicon",
                "embedding_provider": embedding_service.provider,
                "classifier": "softmax_linear_head",
            },
            notes=notes,
            updated_at=utc_now(),
        )
        await model.insert()

        should_activate = (
            auto_activate
            and ml_macro_f1 >= float(min_intent_macro_f1_for_activation)
            and macro_f1_uplift >= float(min_intent_macro_f1_uplift_for_activation)
        )
        if should_activate:
            await self.activate(model_id=str(model.id))
            refreshed = await NLPModelVersion.get(model.id)
            if refreshed:
                model = refreshed

        return model


nlp_model_service = NLPModelService()
