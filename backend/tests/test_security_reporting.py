import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import security
from app.api.api_v1.endpoints.source_discovery_admin import _read_import_file
from app.core.config import settings


def _request(*, body: bytes = b"", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/security/csp-report",
            "headers": headers or [],
            "client": ("127.0.0.1", 1234),
            "scheme": "https",
            "server": ("web.test", 443),
        },
        receive,
    )


class _Upload:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)

    async def read(self, _size: int) -> bytes:
        return next(self._chunks, b"")


class TestSecurityReporting(unittest.IsolatedAsyncioTestCase):
    async def test_csp_report_rejects_oversized_content_before_persistence(self) -> None:
        request = _request(headers=[(b"content-length", b"65537")])
        with patch.object(settings, "SECURITY_CSP_REPORT_MAX_BYTES", 65_536):
            with self.assertRaises(HTTPException) as raised:
                await security.record_csp_report(request)
        self.assertEqual(raised.exception.status_code, 413)

    async def test_csp_report_stores_only_allowlisted_bounded_fields(self) -> None:
        request = _request(
            body=(
                b'{"csp-report":{"document-uri":"https://web.test/page",'
                b'"blocked-uri":"https://evil.test/" ,"extra":"do-not-store"}}'
            )
        )
        stored: dict[str, object] = {}

        class FakeSecurityEvent:
            def __init__(self, **kwargs: object) -> None:
                self.metadata = kwargs["metadata"]

            async def insert(self) -> None:
                stored["row"] = self

        with patch.object(security, "SecurityEvent", FakeSecurityEvent):
            result = await security.record_csp_report(request)
        self.assertEqual(result, {"status": "accepted"})
        row = stored["row"]
        self.assertEqual(row.metadata["report"]["document-uri"], "https://web.test/page")
        self.assertNotIn("extra", row.metadata["report"])

    async def test_source_import_is_limited_while_streaming(self) -> None:
        with patch.object(settings, "SOURCE_DISCOVERY_IMPORT_MAX_BYTES", 1_024):
            with self.assertRaises(HTTPException) as raised:
                await _read_import_file(_Upload([b"a" * 1_000, b"b" * 25]))
        self.assertEqual(raised.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
