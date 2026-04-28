from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings


class ModelArtifactService:
    def resolve_learned_ranker_uri(self) -> str:
        explicit = str(settings.LEARNED_RANKER_ARTIFACT_URI or "").strip()
        if explicit:
            return explicit
        model_path = str(settings.LEARNED_RANKER_MODEL_PATH or "").strip()
        if not model_path:
            return ""
        path = Path(model_path)
        if path.is_absolute():
            return path.as_uri()
        return path.resolve().as_uri()

    def resolve_local_path(self, uri: str) -> Path | None:
        candidate = str(uri or "").strip()
        if not candidate:
            return None
        if "://" not in candidate:
            return Path(candidate).expanduser().resolve()

        parsed = urlparse(candidate)
        if parsed.scheme == "file":
            return Path(parsed.path).expanduser().resolve()
        return None

    def learned_ranker_artifact_exists(self) -> bool:
        uri = self.resolve_learned_ranker_uri()
        if not uri:
            return False
        local_path = self.resolve_local_path(uri)
        if local_path is None:
            return False
        return local_path.exists() and local_path.is_file()

    def ensure_learned_ranker_artifact_ready(self) -> None:
        if not getattr(settings, "LEARNED_RANKER_ENABLED", False):
            return
        if not bool(settings.LEARNED_RANKER_REQUIRE_ARTIFACT_IN_PRODUCTION):
            return
        if not self.learned_ranker_artifact_exists():
            raise RuntimeError(
                "LEARNED_RANKER is enabled but no readable artifact was found via "
                "LEARNED_RANKER_ARTIFACT_URI/LEARNED_RANKER_MODEL_PATH."
            )


model_artifact_service = ModelArtifactService()
