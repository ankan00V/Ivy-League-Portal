from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.application import Application
from app.models.experiment import Experiment, ExperimentAssignment
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.ranking_model_version import RankingModelVersion
from app.models.user import User

MARKER_START = "<!-- DATASET_SNAPSHOT:START -->"
MARKER_END = "<!-- DATASET_SNAPSHOT:END -->"


async def _collect_snapshot() -> dict[str, Any]:
    generated_at = datetime.utcnow()
    opportunities = await Opportunity.find_many().to_list()
    source_counter = Counter(
        str(getattr(item, "source", "") or "unknown").strip().lower() or "unknown"
        for item in opportunities
    )

    return {
        "generated_at": generated_at.isoformat(),
        "snapshot_date": generated_at.strftime("%B %d, %Y"),
        "counts": {
            "opportunities": len(opportunities),
            "applications": int(await Application.find_many().count()),
            "opportunity_interactions": int(await OpportunityInteraction.find_many().count()),
            "experiments": int(await Experiment.find_many().count()),
            "experiment_assignments": int(await ExperimentAssignment.find_many().count()),
            "ranking_model_versions": int(await RankingModelVersion.find_many().count()),
            "drift_reports": int(await ModelDriftReport.find_many().count()),
            "profiles": int(await Profile.find_many().count()),
            "users": int(await User.find_many().count()),
        },
        "source_distribution": dict(sorted(source_counter.items(), key=lambda item: (-item[1], item[0]))),
    }


def _build_markdown(snapshot: dict[str, Any]) -> str:
    counts = dict(snapshot.get("counts") or {})
    source_distribution = dict(snapshot.get("source_distribution") or {})
    lines = [
        "## Dataset Size (Verified Snapshot)",
        f"Snapshot date: **{snapshot.get('snapshot_date') or 'n/a'}**",
        "",
        f"- Opportunities: **{int(counts.get('opportunities') or 0):,}**",
        f"- Applications: **{int(counts.get('applications') or 0):,}**",
        f"- Opportunity interactions: **{int(counts.get('opportunity_interactions') or 0):,}**",
        f"- Experiments: **{int(counts.get('experiments') or 0):,}**",
        f"- Experiment assignments: **{int(counts.get('experiment_assignments') or 0):,}**",
        f"- Ranking model versions: **{int(counts.get('ranking_model_versions') or 0):,}**",
        f"- Drift reports: **{int(counts.get('drift_reports') or 0):,}**",
        f"- Profiles: **{int(counts.get('profiles') or 0):,}**",
        f"- Users: **{int(counts.get('users') or 0):,}**",
        "",
        "Source distribution for opportunities:",
    ]
    for source, count in source_distribution.items():
        lines.append(f"- `{source}`: {int(count):,}")
    return "\n".join(lines).strip()


def _upsert_readme_section(*, readme_path: Path, markdown: str) -> bool:
    content = readme_path.read_text(encoding="utf-8")
    if MARKER_START not in content or MARKER_END not in content:
        return False
    start = content.index(MARKER_START) + len(MARKER_START)
    end = content.index(MARKER_END)
    updated = content[:start] + "\n\n" + markdown + "\n\n" + content[end:]
    readme_path.write_text(updated, encoding="utf-8")
    return True


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Publish dataset snapshot metrics into README and a JSON artifact.")
    parser.add_argument(
        "--readme",
        type=str,
        default=str(REPO_ROOT / "README.md"),
        help="README file containing DATASET_SNAPSHOT markers.",
    )
    parser.add_argument(
        "--artifact",
        type=str,
        default=str(BACKEND_ROOT / "benchmarks" / "dataset_snapshot_latest.json"),
        help="Output JSON artifact path.",
    )
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            Opportunity,
            Application,
            OpportunityInteraction,
            Experiment,
            ExperimentAssignment,
            RankingModelVersion,
            ModelDriftReport,
            Profile,
            User,
        ],
    )
    try:
        snapshot = await _collect_snapshot()
        markdown = _build_markdown(snapshot)

        readme_path = Path(args.readme)
        artifact_path = Path(args.artifact)
        if not artifact_path.is_absolute():
            artifact_path = REPO_ROOT / artifact_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")

        ok = _upsert_readme_section(readme_path=readme_path, markdown=markdown)
        if not ok:
            raise RuntimeError(
                f"README section markers missing. Add {MARKER_START} ... {MARKER_END} to {readme_path}."
            )

        print(
            json.dumps(
                {
                    "status": "ok",
                    "readme": str(readme_path),
                    "artifact": str(artifact_path),
                    "snapshot_date": snapshot.get("snapshot_date"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
