from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

from app.core.config import settings
from app.core.time import utc_now
from app.models.model_artifact_version import ModelArtifactVersion
from app.models.ranking_model_version import RankingModelVersion


@dataclass(frozen=True)
class ArtifactSyncResult:
    uri: str
    local_path: str
    storage_provider: str
    checksum_sha256: str
    verified: bool
    downloaded: bool


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

    def expected_checksum(self, model: RankingModelVersion | None = None) -> str:
        if model is not None and str(model.artifact_checksum_sha256 or "").strip():
            return str(model.artifact_checksum_sha256 or "").strip().lower()
        return str(settings.LEARNED_RANKER_ARTIFACT_CHECKSUM_SHA256 or "").strip().lower()

    def artifact_provider(self, uri: str) -> str:
        candidate = str(uri or "").strip()
        if not candidate:
            return "unknown"
        if "://" not in candidate:
            return "file"
        parsed = urlparse(candidate)
        return (parsed.scheme or "unknown").strip().lower() or "unknown"

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

    def _cache_root(self) -> Path:
        root = Path(settings.MLOPS_MODEL_ARTIFACT_CACHE_DIR or settings.MLOPS_MODEL_ARTIFACT_ROOT).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _cached_target(self, uri: str) -> Path:
        parsed = urlparse(uri)
        leaf = Path(parsed.path or "artifact.bin").name or "artifact.bin"
        digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16]
        return self._cache_root() / digest / leaf

    def file_checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_checksum(self, *, path: Path, expected_sha256: str) -> None:
        expected = str(expected_sha256 or "").strip().lower()
        if not expected:
            return
        actual = self.file_checksum(path)
        if actual != expected:
            raise RuntimeError(
                f"Artifact checksum mismatch for {path.name}: expected {expected}, got {actual}."
            )

    def _download_http(self, uri: str, destination: Path) -> bool:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(uri, timeout=20) as response, destination.open("wb") as handle:  # nosec B310
            shutil.copyfileobj(response, handle)
        return True

    def _download_s3(self, uri: str, destination: Path) -> bool:
        try:
            import boto3  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional runtime dependency
            raise RuntimeError("boto3 is required for s3:// model artifact URIs.") from exc

        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise RuntimeError(f"Invalid s3 artifact URI: {uri}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        session = boto3.session.Session(
            aws_access_key_id=(settings.MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID or None),
            aws_secret_access_key=(settings.MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY or None),
            region_name=(settings.MLOPS_MODEL_ARTIFACT_S3_REGION or None),
        )
        client = session.client(
            "s3",
            endpoint_url=(settings.MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL or None),
        )
        client.download_file(bucket, key, str(destination))
        return True

    def sync_artifact(self, *, uri: str, expected_sha256: str = "") -> ArtifactSyncResult:
        candidate = str(uri or "").strip()
        if not candidate:
            raise RuntimeError("No artifact URI configured.")
        provider = self.artifact_provider(candidate)

        local_path = self.resolve_local_path(candidate)
        downloaded = False
        if local_path is None:
            local_path = self._cached_target(candidate)
            if provider in {"http", "https"}:
                downloaded = self._download_http(candidate, local_path)
            elif provider == "s3":
                downloaded = self._download_s3(candidate, local_path)
            else:
                raise RuntimeError(f"Unsupported artifact provider: {provider}")

        local_path = local_path.expanduser().resolve()
        if not local_path.exists() or not local_path.is_file():
            raise RuntimeError(f"Artifact not found at resolved path: {local_path}")

        self._verify_checksum(path=local_path, expected_sha256=expected_sha256)
        checksum = self.file_checksum(local_path)
        return ArtifactSyncResult(
            uri=candidate,
            local_path=str(local_path),
            storage_provider=provider,
            checksum_sha256=checksum,
            verified=True,
            downloaded=downloaded,
        )

    def learned_ranker_artifact_exists(self) -> bool:
        uri = self.resolve_learned_ranker_uri()
        if not uri:
            return False
        try:
            self.sync_artifact(uri=uri, expected_sha256=self.expected_checksum())
            return True
        except Exception:
            return False

    async def register_artifact(
        self,
        *,
        artifact_uri: str,
        model_version: RankingModelVersion | None = None,
        checksum_sha256: str = "",
        feature_schema: Optional[dict[str, Any]] = None,
        training_metadata: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> ModelArtifactVersion:
        sync = self.sync_artifact(uri=artifact_uri, expected_sha256=checksum_sha256)
        row = ModelArtifactVersion(
            model_family="learned_ranker",
            model_version_id=str(model_version.id) if model_version is not None else None,
            artifact_uri=artifact_uri,
            storage_provider=sync.storage_provider,
            checksum_sha256=sync.checksum_sha256,
            local_cache_path=sync.local_path,
            feature_schema=dict(feature_schema or {}),
            training_metadata=dict(training_metadata or {}),
            metadata=dict(metadata or {}),
            status="verified",
            verified=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        await row.insert()
        if model_version is not None:
            model_version.artifact_uri = artifact_uri
            model_version.artifact_provider = sync.storage_provider
            model_version.artifact_checksum_sha256 = sync.checksum_sha256
            model_version.artifact_manifest = {
                "local_cache_path": sync.local_path,
                "verified": sync.verified,
                "downloaded": sync.downloaded,
                "registered_at": utc_now().isoformat(),
            }
            model_version.serving_ready = True
            await model_version.save()
        return row

    def ensure_model_version_artifact_ready(self, model: RankingModelVersion) -> ArtifactSyncResult | None:
        artifact_uri = str(model.artifact_uri or "").strip()
        if not artifact_uri:
            if bool(settings.LEARNED_RANKER_ENABLED):
                raise RuntimeError(f"Model version {model.id} has no artifact_uri.")
            return None
        return self.sync_artifact(
            uri=artifact_uri,
            expected_sha256=str(model.artifact_checksum_sha256 or "").strip(),
        )

    def ensure_learned_ranker_artifact_ready(self) -> None:
        if not getattr(settings, "LEARNED_RANKER_ENABLED", False):
            return
        if not bool(settings.LEARNED_RANKER_REQUIRE_ARTIFACT_IN_PRODUCTION):
            return
        self.sync_artifact(
            uri=self.resolve_learned_ranker_uri(),
            expected_sha256=self.expected_checksum(),
        )


model_artifact_service = ModelArtifactService()
