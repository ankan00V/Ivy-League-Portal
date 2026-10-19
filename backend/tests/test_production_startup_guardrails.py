import unittest
from unittest.mock import patch

from app.main import validate_production_operational_config


def _complete_production_overrides() -> dict[str, object]:
    """Minimal valid production settings, kept flat to avoid fragile patch stacks."""
    return {
        "ENVIRONMENT": "production",
        "SECRET_KEY": "not-a-placeholder",
        "POSTGRES_ODM_ENABLED": True,
        "SUPABASE_DATABASE_URL": "postgresql://user:pw@db.example.com:5432/postgres",
        "AUTH_SESSION_REQUIRE_SERVER_STATE": True,
        "SCRAPLING_ENABLED": False,
        "CRAWLEE_ENABLED": False,
        "OBSCURA_ENABLED": False,
        "REDIS_URL": "rediss://managed-redis.example.com:6379/0",
        "ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED": True,
        "ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST": "clickhouse.cloud",
        "ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME": "clickhouse-user",
        "ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD": "clickhouse-pass",
        "MLOPS_MODEL_ARTIFACT_S3_REGION": "us-east-1",
        "MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID": "key",
        "MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY": "secret",
        "LLM_API_KEY": "llm-key",
        "GOOGLE_OAUTH_CLIENT_ID": "client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "SMTP_REQUIRE_AUTH": True,
        "SMTP_USER": "smtp-user",
        "SMTP_PASSWORD": "smtp-pass",
    }


class TestProductionStartupGuardrails(unittest.TestCase):
    def test_blocks_localhost_managed_dependencies_in_production(self) -> None:
        overrides = _complete_production_overrides()
        overrides["REDIS_URL"] = "redis://localhost:6379/0"
        with patch.multiple("app.main.settings", **overrides):
            with self.assertRaisesRegex(RuntimeError, "managed Redis"):
                validate_production_operational_config()

    def test_unset_mongodb_url_does_not_block_production(self) -> None:
        """Mongo is retired, so its default local URL must not block a deploy."""
        overrides = _complete_production_overrides()
        overrides["MONGODB_URL"] = "mongodb://localhost:27017"
        with patch.multiple("app.main.settings", **overrides):
            validate_production_operational_config()

    def test_accepts_complete_managed_dependency_config(self) -> None:
        overrides = _complete_production_overrides()
        overrides["MONGODB_URL"] = "mongodb+srv://cluster.mongodb.net"
        with patch.multiple("app.main.settings", **overrides):
            validate_production_operational_config()

    def test_blocks_non_pinning_local_fetchers_in_production(self) -> None:
        overrides = _complete_production_overrides()
        overrides["SCRAPLING_ENABLED"] = True
        with patch.multiple("app.main.settings", **overrides):
            with self.assertRaisesRegex(RuntimeError, "non-pinning local fetchers: SCRAPLING_ENABLED"):
                validate_production_operational_config()


if __name__ == "__main__":
    unittest.main()
