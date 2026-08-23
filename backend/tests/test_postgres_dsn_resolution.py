"""The serving Postgres DSN must be chosen out loud, never guessed.

This exists because of a real incident. The resolution used to be:

    dsn = settings.SUPABASE_DATABASE_URL or settings.NEON_DATABASE_URL

When SUPABASE_DATABASE_URL went missing from .env, that expression did not
fail. It served a stale Neon copy instead - 1,245 active opportunities rather
than 1,797, feature_store_rows at 0 instead of 36,938, and a vector index
holding 121 of 2,245 entries. Readiness passed, the smoke test passed, and the
feed looked fine. Nothing anywhere said "you are on a different database".

An `or` chain cannot distinguish "deliberately use the other database" from
"someone deleted a line", so it must not pick silently.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import config as config_mod
from app.core.config import _dsn_host, resolve_postgres_dsn, settings

SUPA = "postgresql://u:p@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
NEON = "postgresql://u:p@ep-x-pooler.ap-southeast-1.aws.neon.tech/neondb"


class TestPostgresDsnResolution(unittest.TestCase):
    def test_prefers_supabase_when_both_present(self) -> None:
        with (
            patch.object(settings, "SUPABASE_DATABASE_URL", SUPA),
            patch.object(settings, "NEON_DATABASE_URL", NEON),
        ):
            self.assertEqual(resolve_postgres_dsn(), SUPA)

    def test_warns_when_both_are_configured(self) -> None:
        # Ambiguity is the dangerous state: it is the one where deleting a line
        # changes which database serves traffic. It must be audible.
        with (
            patch.object(settings, "SUPABASE_DATABASE_URL", SUPA),
            patch.object(settings, "NEON_DATABASE_URL", NEON),
            self.assertLogs(config_mod.logger, level="WARNING") as logs,
        ):
            resolve_postgres_dsn()
        joined = "\n".join(logs.output)
        self.assertIn("SUPABASE_DATABASE_URL", joined)
        self.assertIn("NEON_DATABASE_URL", joined)

    def test_no_dsn_raises_instead_of_starting(self) -> None:
        with (
            patch.object(settings, "SUPABASE_DATABASE_URL", None),
            patch.object(settings, "NEON_DATABASE_URL", None),
        ):
            with self.assertRaises(RuntimeError) as caught:
                resolve_postgres_dsn()
        self.assertIn("No Postgres DSN", str(caught.exception))

    def test_single_dsn_is_used_without_warning(self) -> None:
        for name, value, other in (
            ("SUPABASE_DATABASE_URL", SUPA, "NEON_DATABASE_URL"),
            ("NEON_DATABASE_URL", NEON, "SUPABASE_DATABASE_URL"),
        ):
            with self.subTest(name=name):
                with (
                    patch.object(settings, name, value),
                    patch.object(settings, other, None),
                    self.assertLogs(config_mod.logger, level="INFO") as logs,
                ):
                    self.assertEqual(resolve_postgres_dsn(), value)
                self.assertFalse(
                    [line for line in logs.output if line.startswith("WARNING")],
                    "an unambiguous configuration should not warn",
                )

    def test_resolution_always_logs_the_host(self) -> None:
        # The incident was invisible because nothing ever named the database in
        # use. The host must appear in the logs on every resolution.
        with (
            patch.object(settings, "SUPABASE_DATABASE_URL", SUPA),
            patch.object(settings, "NEON_DATABASE_URL", None),
            self.assertLogs(config_mod.logger, level="INFO") as logs,
        ):
            resolve_postgres_dsn()
        self.assertIn("aws-0-ap-south-1.pooler.supabase.com:6543", "\n".join(logs.output))

    def test_logged_host_never_leaks_credentials(self) -> None:
        host = _dsn_host("postgresql://postgres.abc:sup3rs3cret@host.example.com:6543/postgres")
        self.assertEqual(host, "host.example.com:6543")
        self.assertNotIn("sup3rs3cret", host)


if __name__ == "__main__":
    unittest.main()
