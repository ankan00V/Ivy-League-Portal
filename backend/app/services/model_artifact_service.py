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
    APPROVED_STATUS = "approved"
    REJECTED_STATUS = "rejected"
    VERIFIED_STATUS = "verified"

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
            status=self.VERIFIED_STATUS,
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
            model_version.serving_ready = False
            await model_version.save()
        return row

    async def approve_artifact(self, *, artifact_id: str, reviewer: str, notes: str = "") -> ModelArtifactVersion:
        row = await ModelArtifactVersion.get(artifact_id)
        if row is None:
            raise ValueError("artifact_not_found")

        sync = self.sync_artifact(
            uri=row.artifact_uri,
            expected_sha256=str(row.checksum_sha256 or "").strip(),
        )
        now = utc_now()
        row.storage_provider = sync.storage_provider
        row.checksum_sha256 = sync.checksum_sha256
        row.local_cache_path = sync.local_path
        row.verified = True
        row.status = self.APPROVED_STATUS
        row.reviewer = reviewer.strip() or "unknown"
        row.review_notes = notes.strip() or None
        row.reviewed_at = now
        row.updated_at = now
        await row.save()

        if row.model_version_id:
            model = await RankingModelVersion.get(row.model_version_id)
            if model is not None:
                self._attach_artifact_to_model(model=model, artifact=row, sync=sync)
                model.serving_ready = True
                await model.save()
        return row

    async def reject_artifact(self, *, artifact_id: str, reviewer: str, notes: str = "") -> ModelArtifactVersion:
        row = await ModelArtifactVersion.get(artifact_id)
        if row is None:
            raise ValueError("artifact_not_found")
        now = utc_now()
        row.status = self.REJECTED_STATUS
        row.reviewer = reviewer.strip() or "unknown"
        row.review_notes = notes.strip() or None
        row.reviewed_at = now
        row.updated_at = now
        await row.save()
        return row

    async def compare_artifacts(self, *, artifact_id_a: str, artifact_id_b: str) -> dict[str, Any]:
        left = await ModelArtifactVersion.get(artifact_id_a)
        right = await ModelArtifactVersion.get(artifact_id_b)
        if left is None or right is None:
            raise ValueError("artifact_not_found")

        left_metrics = dict((left.training_metadata or {}).get("metrics") or {})
        right_metrics = dict((right.training_metadata or {}).get("metrics") or {})
        metric_keys = sorted(set(left_metrics) | set(right_metrics))
        metric_deltas = {
            key: self._safe_float(right_metrics.get(key)) - self._safe_float(left_metrics.get(key))
            for key in metric_keys
        }
        left_features = set((left.feature_schema or {}).get("features") or (left.feature_schema or {}).keys())
        right_features = set((right.feature_schema or {}).get("features") or (right.feature_schema or {}).keys())
        return {
            "left": self._artifact_summary(left),
            "right": self._artifact_summary(right),
            "metric_deltas_right_minus_left": {key: round(value, 6) for key, value in metric_deltas.items()},
            "feature_schema": {
                "added": sorted(right_features - left_features),
                "removed": sorted(left_features - right_features),
                "common_count": len(left_features & right_features),
            },
            "same_checksum": bool((left.checksum_sha256 or "") and left.checksum_sha256 == right.checksum_sha256),
        }

    async def rollback_artifact(
        self,
        *,
        model_version_id: str | None = None,
        artifact_id: str | None = None,
    ) -> ModelArtifactVersion:
        if artifact_id:
            row = await ModelArtifactVersion.get(artifact_id)
            if row is None:
                raise ValueError("artifact_not_found")
        else:
            filters: list[Any] = [ModelArtifactVersion.status == self.APPROVED_STATUS]
            if model_version_id:
                filters.append(ModelArtifactVersion.model_version_id == model_version_id)
            rows = await ModelArtifactVersion.find_many(*filters).sort("-reviewed_at", "-created_at").limit(2).to_list()
            if not rows:
                raise ValueError("rollback_target_not_found")
            row = rows[1] if len(rows) > 1 else rows[0]

        if row.status != self.APPROVED_STATUS:
            raise ValueError("artifact_not_approved")
        sync = self.sync_artifact(
            uri=row.artifact_uri,
            expected_sha256=str(row.checksum_sha256 or "").strip(),
        )
        row.promoted_at = utc_now()
        row.updated_at = utc_now()
        await row.save()
        if row.model_version_id:
            model = await RankingModelVersion.get(row.model_version_id)
            if model is not None:
                self._attach_artifact_to_model(model=model, artifact=row, sync=sync)
                model.serving_ready = True
                await model.save()
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

    async def require_model_version_artifact_approved(self, model: RankingModelVersion) -> None:
        artifact_uri = str(model.artifact_uri or "").strip()
        if not artifact_uri:
            return

        row = None
        if model.id is not None:
            row = await ModelArtifactVersion.find_one(
                ModelArtifactVersion.status == self.APPROVED_STATUS,
                ModelArtifactVersion.model_version_id == str(model.id),
            )
        if row is None:
            row = await ModelArtifactVersion.find_one(
                ModelArtifactVersion.status == self.APPROVED_STATUS,
                ModelArtifactVersion.artifact_uri == artifact_uri,
            )
        if row is None:
            raise RuntimeError(f"Model version {model.id} artifact is not approved for activation.")

    def ensure_learned_ranker_artifact_ready(self) -> None:
        if not getattr(settings, "LEARNED_RANKER_ENABLED", False):
            return
        if not bool(settings.LEARNED_RANKER_REQUIRE_ARTIFACT_IN_PRODUCTION):
            return
        self.sync_artifact(
            uri=self.resolve_learned_ranker_uri(),
            expected_sha256=self.expected_checksum(),
        )

    def _attach_artifact_to_model(
        self,
        *,
        model: RankingModelVersion,
        artifact: ModelArtifactVersion,
        sync: ArtifactSyncResult,
    ) -> None:
        model.artifact_uri = artifact.artifact_uri
        model.artifact_provider = sync.storage_provider
        model.artifact_checksum_sha256 = sync.checksum_sha256
        model.feature_schema = dict(artifact.feature_schema or model.feature_schema or {})
        manifest = dict(model.artifact_manifest or {})
        manifest.update(
            {
                "artifact_version_id": str(artifact.id),
                "artifact_status": artifact.status,
                "local_cache_path": sync.local_path,
                "verified": sync.verified,
                "downloaded": sync.downloaded,
                "approved_at": artifact.reviewed_at.isoformat() if artifact.reviewed_at else None,
                "promoted_at": utc_now().isoformat(),
            }
        )
        model.artifact_manifest = manifest

    def _artifact_summary(self, row: ModelArtifactVersion) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "model_family": row.model_family,
            "model_version_id": row.model_version_id,
            "artifact_uri": row.artifact_uri,
            "checksum_sha256": row.checksum_sha256,
            "status": row.status,
            "verified": bool(row.verified),
            "reviewer": row.reviewer,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "training_window": {
                "start": (row.training_metadata or {}).get("training_window_start"),
                "end": (row.training_metadata or {}).get("training_window_end"),
            },
            "code_version": (row.training_metadata or {}).get("code_version"),
        }

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0


model_artifact_service = ModelArtifactService()
