from __future__ import annotations

import logging
import re
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from app.core.config import settings
from app.services.domain_vocabulary import vocabulary_skill_tags

logger = logging.getLogger(__name__)

DEFAULT_SKILL_TAGS = (
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "node",
    "sql",
    "aws",
    "machine learning",
    "data science",
)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+.#-]*")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(str(text or ""))


def token_feature_rows(tokens: Iterable[str]) -> list[str]:
    values = [str(token) for token in tokens]
    rows: list[str] = []
    for index, token in enumerate(values):
        lowered = token.lower()
        context = values[max(0, index - 2) : min(len(values), index + 3)]
        previous = values[index - 1].lower() if index else "<bos>"
        following = values[index + 1].lower() if index + 1 < len(values) else "<eos>"
        rows.append(
            " ".join(
                [
                    f"token={lowered}",
                    f"prev={previous}",
                    f"next={following}",
                    f"prefix={lowered[:3]}",
                    f"suffix={lowered[-3:]}",
                    f"upper={int(token.isupper())}",
                    f"digit={int(any(character.isdigit() for character in token))}",
                    f"context={'_'.join(item.lower() for item in context)}",
                ]
            )
        )
    return rows


def fallback_skill_tags(text: str) -> list[str]:
    lowered = str(text or "").lower()
    return [skill for skill in DEFAULT_SKILL_TAGS if skill in lowered]


class SkillExtractor:
    def __init__(self) -> None:
        self._artifact: dict[str, Any] | None = None
        self._loaded_path: Path | None = None
        self._load_attempted = False
        self._lock = Lock()

    def _artifact_path(self) -> Path:
        return Path(str(settings.SKILL_EXTRACTOR_MODEL_PATH or "")).expanduser()

    @staticmethod
    def _resolve_model_dir(value: str) -> Path:
        """Resolve a stored model_dir, relative to the repo root when relative.

        Older artifacts baked in an absolute path like
        /Users/<name>/Developer/ivy league/backend/models/... which breaks the
        moment the checkout moves. This project has already moved once, from
        Desktop to Developer, and a broken path here fails quietly: the loader
        logs a warning and silently degrades to keyword extraction, so the model
        looks present while contributing nothing. Absolute paths still work, so
        artifacts trained before this change keep loading.
        """
        candidate = Path(str(value or "")).expanduser()
        if candidate.is_absolute():
            return candidate
        return (Path(__file__).resolve().parents[3] / candidate).resolve()

    def _load_artifact(self) -> dict[str, Any] | None:
        if not settings.SKILL_EXTRACTOR_ENABLED:
            return None

        path = self._artifact_path()
        with self._lock:
            if self._load_attempted and self._loaded_path == path:
                return self._artifact
            self._load_attempted = True
            self._loaded_path = path
            self._artifact = None

            if not path.is_file():
                return None
            try:
                import joblib  # type: ignore

                artifact = joblib.load(path)
                if not isinstance(artifact, dict) or artifact.get("schema_version") != 1:
                    raise ValueError("unsupported skill extractor artifact")
                model_type = str(artifact.get("model_type") or "linear")
                if model_type == "linear" and not hasattr(artifact.get("pipeline"), "predict_proba"):
                    raise ValueError("skill extractor artifact has no probabilistic classifier")
                if model_type == "transformer" and not self._resolve_model_dir(str(artifact.get("model_dir") or "")).is_dir():
                    raise ValueError("skill extractor transformer directory is unavailable")
                self._artifact = artifact
            except Exception as exc:
                logger.warning("Skill extractor artifact unavailable; using keyword fallback: %s", exc)
            return self._artifact

    @staticmethod
    def _learned_skill_tags(tokens: list[str], artifact: dict[str, Any]) -> list[str]:
        if not tokens:
            return []
        pipeline = artifact["pipeline"]
        classes = [str(label) for label in pipeline.classes_]
        probabilities = pipeline.predict_proba(token_feature_rows(tokens))
        confidence_floor = float(artifact.get("min_confidence", settings.SKILL_EXTRACTOR_MIN_CONFIDENCE))

        tags: list[str] = []
        active: list[str] = []
        for token, row in zip(tokens, probabilities):
            best_index = int(row.argmax())
            label = classes[best_index]
            confidence = float(row[best_index])
            is_entity = label in {"B", "I"} and confidence >= confidence_floor

            if not is_entity:
                if active:
                    tags.append(" ".join(active))
                    active = []
                continue
            if label == "B" and active:
                tags.append(" ".join(active))
                active = []
            active.append(token.lower())

        if active:
            tags.append(" ".join(active))
        return tags

    @staticmethod
    def _lexicon_skill_tags(tokens: list[str], artifact: dict[str, Any]) -> list[str]:
        phrases = [str(value).strip().lower().split() for value in artifact.get("skill_lexicon", [])]
        phrases = [phrase for phrase in phrases if phrase]
        phrases.sort(key=len, reverse=True)
        lowered = [token.lower() for token in tokens]
        tags: list[str] = []
        index = 0
        while index < len(lowered):
            matched = next((phrase for phrase in phrases if lowered[index : index + len(phrase)] == phrase), None)
            if matched is None:
                index += 1
                continue
            tags.append(" ".join(matched))
            index += len(matched)
        return tags

    @staticmethod
    def _transformer_skill_tags(tokens: list[str], artifact: dict[str, Any]) -> list[str]:
        runtime = artifact.get("_runtime")
        if not isinstance(runtime, dict):
            import torch  # type: ignore
            from transformers import AutoModelForTokenClassification, AutoTokenizer  # type: ignore

            model_dir = str(SkillExtractor._resolve_model_dir(str(artifact["model_dir"])))
            device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
            tokenizer = AutoTokenizer.from_pretrained(model_dir)
            model = AutoModelForTokenClassification.from_pretrained(model_dir).to(device)
            model.eval()
            runtime = {"torch": torch, "device": device, "tokenizer": tokenizer, "model": model}
            artifact["_runtime"] = runtime

        torch = runtime["torch"]
        tokenizer = runtime["tokenizer"]
        model = runtime["model"]
        device = runtime["device"]
        encoded = tokenizer(tokens, is_split_into_words=True, return_tensors="pt", truncation=True, max_length=256)
        word_ids = encoded.word_ids(batch_index=0)
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.no_grad():
            probabilities = torch.softmax(model(**encoded).logits[0], dim=-1).detach().cpu().numpy()

        id_to_label = {int(key): str(value) for key, value in dict(artifact.get("id_to_label") or {}).items()}
        confidence_floor = float(artifact.get("min_confidence", settings.SKILL_EXTRACTOR_MIN_CONFIDENCE))
        labels = ["O"] * len(tokens)
        seen_words: set[int] = set()
        for index, word_id in enumerate(word_ids):
            if word_id is None or word_id in seen_words:
                continue
            seen_words.add(word_id)
            row = probabilities[index]
            class_id = int(row.argmax())
            label = id_to_label.get(class_id, "O")
            if label in {"B", "I"} and float(row[class_id]) >= confidence_floor:
                labels[word_id] = label

        tags: list[str] = []
        active: list[str] = []
        for token, label in zip(tokens, labels):
            if label == "O":
                if active:
                    tags.append(" ".join(active))
                    active = []
                continue
            if label == "B" and active:
                tags.append(" ".join(active))
                active = []
            active.append(token.lower())
        if active:
            tags.append(" ".join(active))
        return tags

    def extract(self, text: str, *, max_tags: int = 12) -> list[str]:
        values = fallback_skill_tags(text)
        # Supplementary vocabularies for domains the trained artifact never saw.
        # Applied before the artifact check because it is the only signal for an
        # AYUSH posting, which otherwise extracts to [] - a silent result that
        # leaves the whole domain with no demand table and no questionnaire.
        values.extend(vocabulary_skill_tags(text))
        artifact = self._load_artifact()
        if artifact is None:
            return values[:max_tags]

        tokens = tokenize(text)[:500]
        try:
            values.extend(self._lexicon_skill_tags(tokens, artifact))
            if str(artifact.get("model_type") or "linear") == "transformer":
                values.extend(self._transformer_skill_tags(tokens, artifact))
            else:
                values.extend(self._learned_skill_tags(tokens, artifact))
        except Exception as exc:
            logger.warning("Skill extractor inference failed; using keyword fallback: %s", exc)

        deduplicated: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(str(value).split()).lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(normalized)
        return deduplicated[:max_tags]


skill_extractor = SkillExtractor()
