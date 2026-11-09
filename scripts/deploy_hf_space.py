#!/usr/bin/env python3
"""Stage and upload the VidyaVerse API to a Hugging Face Docker Space.

The Space repository needs the backend source at its root alongside the Space
metadata and image. Rather than duplicating backend/ in this repository, the
folder is assembled from it at deploy time.

Secrets are set one by one through the Hub API and never printed: this script
reports key names only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEPLOY = ROOT / "deploy" / "huggingface"

SKIP_DIRS = {
    "venv", ".venv", "models", "bin", "backups", "storage",
    ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache",
    ".claude", ".claude-flow",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".duckdb", ".sqlite"}
SKIP_FILES = {".env", "server_logs.txt", ".DS_Store", ".env.bak.premigration"}

# Values copied from the local environment when present. Anything absent is
# simply not sent, so the Space keeps whatever the platform or code default is.
PASS_THROUGH = [
    "DATABASE_URL", "DATABASE_URL_UNPOOLED",
    "REDIS_URL", "REDIS_CACHE_URL", "REDIS_FEATURE_STORE_URL",
    "SECRET_KEY",
    "NEON_AUTH_BASE_URL", "NEON_AUTH_JWKS_URL", "NEON_AUTH_COOKIE_SECRET",
    "NEON_AUTH_BRIDGE_SECRET",
    "LLM_API_KEY", "LLM_API_BASE_URL", "LLM_MODEL", "LLM_PROVIDER",
    "OPENAI_API_KEY", "OPENROUTER_API_KEY",
    "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI",
    "TURNSTILE_SECRET_KEY", "RESEND_API_KEY", "RESEND_FROM_EMAIL",
    "AUTH_OTP_FROM_NAME", "AUTH_SUPPORT_EMAIL", "AUTH_COMPANY_NAME",
    "MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL", "MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID",
    "MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY", "MLOPS_MODEL_ARTIFACT_S3_REGION",
    "MODEL_ARTIFACT_BUCKET",
    "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_MODEL_VERSION",
]

# Forced for a deployed instance. The production startup guard rejects the
# local development posture, and the background subsystems would compete for a
# free CPU Space's two vCPUs with the request path.
FORCED = {
    "ENVIRONMENT": "production",
    "AUTH_SESSION_ENABLED": "true",
    "AUTH_SESSION_COOKIE_ENABLED": "true",
    "AUTH_SESSION_COOKIE_NAME": "vidyaverse_session",
    "AUTH_SESSION_COOKIE_SECURE": "true",
    "AUTH_SESSION_COOKIE_SAMESITE": "lax",
    "AUTH_COOKIE_ONLY_MODE": "true",
    "AUTH_SESSION_STORE_ENABLED": "true",
    "AUTH_SESSION_REQUIRE_SERVER_STATE": "true",
    "AUTH_SESSION_BIND_DEVICE": "true",
    "CSRF_PROTECTION_ENABLED": "true",
    "CSRF_DOUBLE_SUBMIT_ENABLED": "true",
    "CSRF_ENFORCE_ON_AUTH_COOKIE": "true",
    "SECURITY_CSP_ENFORCE_STRICT_IN_PRODUCTION": "false",
    # Fetchers whose networking cannot be pinned to a validated address, and the
    # paid providers that failed every URL on the last sweep.
    "SCRAPLING_ENABLED": "false",
    "CRAWLEE_ENABLED": "false",
    "OBSCURA_ENABLED": "false",
    "FIRECRAWL_ENABLED": "false",
    "BROWSER_USE_ENABLED": "false",
    # Scheduled work stays off: a free Space cannot carry ingestion and serving.
    "DISCOVERY_ENABLED": "false",
    "SCRAPER_AUTORUN_ENABLED": "false",
    "MLOPS_AUTORUN_ENABLED": "false",
    "MLOPS_ALERTS_ENABLED": "false",
    "MLOPS_INCIDENT_AUTO_CREATE": "false",
    "MLOPS_BOOTSTRAP_ACTIVE_MODEL_ON_STARTUP": "false",
    "ANALYTICS_WAREHOUSE_ENABLED": "false",
    "ANALYTICS_WAREHOUSE_EXPORT_ENABLED": "false",
    "ANALYTICS_WAREHOUSE_AUTORUN_ENABLED": "false",
    "EMBEDDING_AUTORUN_ENABLED": "false",
    "DESCRIPTION_ENRICHMENT_ENABLED": "false",
    "EXPERIMENT_AUTO_GRADUATION_ENABLED": "false",
    "OPPORTUNITY_STATUS_AUTORUN_ENABLED": "false",
    "JOBS_ENABLED": "false",
    # The learned ranker is not validated; semantic retrieval is the mode the
    # project trusts, and loading the artifact would need S3 at startup.
    "LEARNED_RANKER_ENABLED": "false",
    "LEARNED_RANKER_REQUIRE_LOADED_IN_PRODUCTION": "false",
    "LEARNED_RANKER_REQUIRE_ARTIFACT_IN_PRODUCTION": "false",
    "SMTP_REQUIRE_AUTH": "false",
    "TURNSTILE_ENABLED": "false",
    "ADMIN_BOOTSTRAP_ENABLED": "false",
    "RAG_WARMUP_ON_STARTUP": "false",
}


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def stage(destination: Path) -> tuple[int, int]:
    def ignore(directory: str, names: list[str]) -> set[str]:
        dropped = set()
        for name in names:
            entry = Path(directory) / name
            if entry.is_dir() and name in SKIP_DIRS:
                dropped.add(name)
            elif entry.is_file() and (name in SKIP_FILES or entry.suffix in SKIP_SUFFIXES):
                dropped.add(name)
        return dropped

    shutil.copytree(BACKEND, destination, ignore=ignore)
    # Space metadata and image replace nothing in backend/: the compose image
    # keeps using backend/Dockerfile.
    shutil.copy2(DEPLOY / "Dockerfile", destination / "Dockerfile")
    shutil.copy2(DEPLOY / "README.md", destination / "README.md")

    files = 0
    size = 0
    for path in destination.rglob("*"):
        if path.is_file():
            files += 1
            size += path.stat().st_size
    return files, size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-name", default="vidyaverse-api")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--frontend-origin", action="append", default=[],
                        help="Public origin of the frontend; may be repeated.")
    parser.add_argument("--skip-upload", action="store_true",
                        help="Stage and report only.")
    parser.add_argument("--skip-secrets", action="store_true")
    args = parser.parse_args()

    from huggingface_hub import HfApi

    api = HfApi()
    who = api.whoami()
    username = who.get("name")
    repo_id = f"{username}/{args.repo_name}"
    space_host = f"{username}-{args.repo_name}.hf.space"
    space_url = f"https://{space_host}"

    local = load_env(ROOT / ".env")
    local.update(load_env(BACKEND / ".env"))  # backend-specific values win

    origins = [o.rstrip("/") for o in args.frontend_origin] or ["http://localhost:3000"]
    allowed_hosts = ["localhost", "127.0.0.1", space_host]
    if "localhost:3000" in origins[0]:
        allowed_hosts.append("localhost:3000")

    secrets: dict[str, str] = {}
    for key in PASS_THROUGH:
        value = local.get(key)
        if value:
            secrets[key] = value
    secrets.update(FORCED)
    secrets["ALLOWED_HOSTS"] = json.dumps(allowed_hosts)
    secrets["BACKEND_CORS_ORIGINS"] = json.dumps(origins)
    secrets["CSRF_TRUSTED_ORIGINS"] = json.dumps(origins)

    workdir = Path(tempfile.mkdtemp(prefix="vidyaverse-space-"))
    staged = workdir / "space"
    try:
        files, size = stage(staged)
        print(f"staged {files} files, {size / 1024:.0f} KiB from backend/")
        if args.skip_upload:
            print(f"staged at {staged}")
            return 0

        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="docker",
            private=args.private,
            exist_ok=True,
        )
        print(f"space: https://huggingface.co/spaces/{repo_id}")

        api.upload_folder(
            folder_path=str(staged),
            repo_id=repo_id,
            repo_type="space",
            commit_message="Deploy VidyaVerse API to Hugging Face Space",
        )
        print("upload complete")

        if not args.skip_secrets:
            for key, value in sorted(secrets.items()):
                api.add_space_secret(repo_id=repo_id, key=key, value=value)
            print(f"set {len(secrets)} Space secrets:")
            print("  " + ", ".join(sorted(secrets)))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"app URL: {space_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
