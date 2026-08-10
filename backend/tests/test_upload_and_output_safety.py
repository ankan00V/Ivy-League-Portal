"""Upload validation and output-escaping guards.

Two owner-requested properties, locked so they cannot silently regress:

1. Every upload is checked for type AND size, and stored where it can never be
   executed or served as a static asset.
2. Anything a user submits is escaped or stripped before it reaches a page.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
USERS_PATH = BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "users.py"
MAIN_PATH = BACKEND_ROOT / "app" / "main.py"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"


class TestUploadTypeAndSize:
    def test_extension_is_allowlisted_not_blocklisted(self):
        from app.api.api_v1.endpoints.users import ALLOWED_RESUME_EXTENSIONS

        assert ALLOWED_RESUME_EXTENSIONS == {".txt", ".pdf", ".docx", ".doc"}
        for dangerous in (".exe", ".sh", ".php", ".js", ".html", ".svg", ".py"):
            assert dangerous not in ALLOWED_RESUME_EXTENSIONS

    def test_size_is_enforced_while_reading_not_after(self):
        """Buffering first and measuring after makes the cap free to exceed."""
        source = USERS_PATH.read_text(encoding="utf-8")
        assert "_RESUME_READ_CHUNK_BYTES" in source
        assert "await file.read(_RESUME_READ_CHUNK_BYTES)" in source, (
            "the body must be read in bounded chunks"
        )
        upload = source.split("async def upload_resume")[1][:2500]
        abort = upload.find("received > size_limit_bytes")
        joined = upload.find('content = b"".join(chunks)')
        assert abort != -1 and joined != -1
        assert abort < joined, "the size check must abort before the body is assembled"

    def test_unbounded_read_is_gone(self):
        upload = USERS_PATH.read_text(encoding="utf-8").split("async def upload_resume")[1][:2500]
        assert "await file.read()" not in upload, (
            "an argument-less read() buffers the entire upload before any size check"
        )

    def test_stored_content_type_is_derived_from_extension(self):
        from app.api.api_v1.endpoints.users import (
            ALLOWED_RESUME_EXTENSIONS,
            _RESUME_CONTENT_TYPES,
        )

        assert set(_RESUME_CONTENT_TYPES) == ALLOWED_RESUME_EXTENSIONS
        # None of them may render inline in a browser.
        for value in _RESUME_CONTENT_TYPES.values():
            assert value not in {"text/html", "image/svg+xml", "application/xhtml+xml"}
        source = USERS_PATH.read_text(encoding="utf-8")
        assert "resume_content_type = _RESUME_CONTENT_TYPES.get(extension" in source
        assert "profile.resume_content_type = (file.content_type" not in source, (
            "the client must not choose how its own file is interpreted on download"
        )

    def test_stored_filename_is_server_generated(self):
        """The user's filename never reaches the filesystem, so no traversal."""
        source = USERS_PATH.read_text(encoding="utf-8")
        assert 'storage_key = f"{str(current_user.id)}_{uuid4().hex}{extension}"' in source

    def test_uploads_are_never_served_as_static_assets(self):
        """No StaticFiles mount means an uploaded file can never be executed."""
        main_source = MAIN_PATH.read_text(encoding="utf-8")
        assert "StaticFiles" not in main_source
        assert ".mount(" not in main_source

    def test_download_forces_attachment(self):
        source = USERS_PATH.read_text(encoding="utf-8")
        assert "FileResponse(" in source
        assert "filename=" in source, "FileResponse(filename=...) sets Content-Disposition: attachment"


class TestOutputEscaping:
    def test_no_raw_html_sink_carries_interpolated_data(self):
        """React escapes by default; the only risk is an explicit raw-HTML sink."""
        offenders: list[str] = []
        for path in list(FRONTEND_SRC.rglob("*.tsx")) + list(FRONTEND_SRC.rglob("*.ts")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for sink in ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "document.write"):
                for match in re.finditer(re.escape(sink), text):
                    window = text[match.start() : match.start() + 400]
                    # A template literal with ${...} is interpolating something.
                    if "${" in window:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}: {sink}")
        assert not offenders, f"raw HTML sink with interpolated content: {offenders}"

    def test_scraped_text_is_stripped_then_unescaped_then_restripped(self):
        """Entity decoding after stripping can re-introduce tags."""
        from app.services.scraper import _clean_description

        assert "<script>" not in _clean_description("<script>alert(1)</script>hello")
        # Double-encoded: strip does nothing, unescape reveals a live tag.
        cleaned = _clean_description("&lt;script&gt;alert(1)&lt;/script&gt; real text")
        assert "<script>" not in cleaned and "</script>" not in cleaned
        assert "real text" in cleaned

    def test_entities_are_decoded_for_display(self):
        from app.services.scraper import _clean_description

        assert "&amp;" not in _clean_description("Research &amp; Development")
        assert "Research & Development" in _clean_description("Research &amp; Development")
