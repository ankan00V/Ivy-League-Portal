from __future__ import annotations

from unittest.mock import patch

from scripts import check_production_infra_readiness as readiness


def test_local_url_detection_catches_docker_and_loopback_hosts() -> None:
    assert readiness._is_local_url("mongodb://localhost:27017", schemes=("mongodb", "mongodb+srv"))
    assert readiness._is_local_url("redis://127.0.0.1:6379/0", schemes=("redis", "rediss"))
    assert readiness._is_local_url("http://minio:9000", schemes=("http", "https"))
    assert readiness._is_local_url("https://clickhouse:8443", schemes=("http", "https"))


def test_local_url_detection_allows_managed_hosts() -> None:
    assert not readiness._is_local_url("mongodb+srv://cluster.example.mongodb.net/app", schemes=("mongodb", "mongodb+srv"))
    assert not readiness._is_local_url("rediss://cache.example.com:6379/0", schemes=("redis", "rediss"))
    assert not readiness._is_local_url("https://bi.example.com", schemes=("http", "https"))


def test_bi_tool_rejects_local_url_when_managed_infra_required() -> None:
    with patch.object(readiness, "analytics_bi_tool_url", return_value="http://localhost:3001"):
        result = readiness._check_bi_tool(require_managed=True)

    assert result["name"] == "bi_tool"
    assert result["ok"] is False
    assert result["detail"] == "BI URL points at local/dev infrastructure"


def test_clickhouse_rejects_compose_host_when_managed_infra_required() -> None:
    with patch.object(readiness.settings, "ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED", True), patch.object(
        readiness.settings, "ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST", "clickhouse"
    ):
        result = readiness._check_clickhouse(require_managed=True)

    assert result["name"] == "clickhouse"
    assert result["ok"] is False
    assert result["detail"] == "ClickHouse host points at local/dev infrastructure"
