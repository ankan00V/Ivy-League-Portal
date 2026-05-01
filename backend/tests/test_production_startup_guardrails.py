import unittest
from unittest.mock import patch

from app.main import validate_production_operational_config


class TestProductionStartupGuardrails(unittest.TestCase):
    def test_blocks_localhost_managed_dependencies_in_production(self) -> None:
        with (
            patch("app.main.settings.ENVIRONMENT", "production"),
            patch("app.main.settings.SECRET_KEY", "not-a-placeholder"),
            patch("app.main.settings.MONGODB_URL", "mongodb://localhost:27017"),
        ):
            with self.assertRaisesRegex(RuntimeError, "managed MongoDB"):
                validate_production_operational_config()

    def test_accepts_complete_managed_dependency_config(self) -> None:
        with (
            patch("app.main.settings.ENVIRONMENT", "production"),
            patch("app.main.settings.SECRET_KEY", "not-a-placeholder"),
            patch("app.main.settings.MONGODB_URL", "mongodb+srv://cluster.mongodb.net"),
            patch("app.main.settings.REDIS_URL", "rediss://managed-redis.example.com:6379/0"),
            patch("app.main.settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED", True),
            patch("app.main.settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST", "clickhouse.cloud"),
            patch("app.main.settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME", "clickhouse-user"),
            patch("app.main.settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD", "clickhouse-pass"),
            patch("app.main.settings.MLOPS_MODEL_ARTIFACT_S3_REGION", "us-east-1"),
            patch("app.main.settings.MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID", "key"),
            patch("app.main.settings.MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY", "secret"),
            patch("app.main.settings.LLM_API_KEY", "llm-key"),
            patch("app.main.settings.GOOGLE_OAUTH_CLIENT_ID", "client"),
            patch("app.main.settings.GOOGLE_OAUTH_CLIENT_SECRET", "secret"),
            patch("app.main.settings.SMTP_REQUIRE_AUTH", True),
            patch("app.main.settings.SMTP_USER", "smtp-user"),
            patch("app.main.settings.SMTP_PASSWORD", "smtp-pass"),
        ):
            validate_production_operational_config()


if __name__ == "__main__":
    unittest.main()
