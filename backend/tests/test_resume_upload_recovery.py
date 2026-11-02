import io
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.api_v1.endpoints import users


class TestResumeUploadRecovery(unittest.IsolatedAsyncioTestCase):
    async def upload(self, directory, profile, storage_error=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(users, "_get_or_create_profile_for_user", AsyncMock(return_value=profile)))
            stack.enter_context(patch.object(users, "_resume_storage_dir", return_value=directory, side_effect=storage_error))
            stack.enter_context(patch.object(users, "_extract_resume_text", return_value=""))
            stack.enter_context(patch.object(users, "_sync_profile_identity"))
            stack.enter_context(patch.object(users, "_compute_onboarding_status", return_value=(False, 80, [], "details")))
            stack.enter_context(patch.object(users, "score_profile_with_outcomes", AsyncMock(return_value=SimpleNamespace(total=10))))
            stack.enter_context(patch.object(users.cache_manager, "invalidate_after_profile_update", AsyncMock()))
            return await users.upload_resume(
                file=UploadFile(filename="new.txt", file=io.BytesIO(b"test resume")),
                current_user=SimpleNamespace(id="test-user"),
            )

    async def test_replacement_removes_old_file_only_after_successful_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.txt"
            old.write_bytes(b"old resume")

            async def save():
                self.assertTrue(old.exists(), "Existing resume must survive until the database save")

            profile = SimpleNamespace(resume_storage_key="old.txt", save=AsyncMock(side_effect=save))
            result = await self.upload(root, profile)
            self.assertFalse(old.exists())
            self.assertEqual((root / result.resume_storage_key).read_bytes(), b"test resume")

    async def test_failed_save_preserves_the_existing_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.txt"
            old.write_bytes(b"old resume")
            profile = SimpleNamespace(resume_storage_key="old.txt", save=AsyncMock(side_effect=RuntimeError("database unavailable")))
            with self.assertRaises(RuntimeError):
                await self.upload(root, profile)
            self.assertEqual(old.read_bytes(), b"old resume")

    async def test_unwritable_storage_returns_actionable_service_error(self):
        profile = SimpleNamespace(resume_storage_key=None, save=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await self.upload(Path("/not-used"), profile, PermissionError("not writable"))
        self.assertEqual(error.exception.status_code, 503)
        self.assertIn("Resume storage", error.exception.detail)
        profile.save.assert_not_awaited()
