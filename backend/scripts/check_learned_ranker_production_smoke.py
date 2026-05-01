from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.services.model_artifact_service import model_artifact_service
from app.services.personalization.learned_ranker import learned_ranker


def main() -> None:
    if not settings.LEARNED_RANKER_ENABLED:
        raise SystemExit("LEARNED_RANKER_ENABLED must be true for the production smoke test.")
    sync = model_artifact_service.sync_artifact(
        uri=model_artifact_service.resolve_learned_ranker_uri(),
        expected_sha256=model_artifact_service.expected_checksum(),
    )
    learned_ranker.ensure_loaded_for_production()
    print(
        json.dumps(
            {
                "status": "ok",
                "artifact_uri": sync.uri,
                "local_path": sync.local_path,
                "checksum_sha256": sync.checksum_sha256,
                "storage_provider": sync.storage_provider,
                "loaded": learned_ranker.is_loaded,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
