"""A board headed "Top 10 Students" must contain students.

The live board listed Demo Industry Recruiter at #7, Demo Institution Registrar
at #8 and two Demo Academicians at #9 and #10, under that heading, because the
query was `Profile.find_all()` with no filter at all. The sidebar beside it read
"Rank #2 of 8" - the ranking summary scopes by account type and always has - so
one screen carried two numbers computed from different populations and neither
said which.

Three further faults were visible in the same screenshot and are pinned here
too: the same account appeared twice (@ankanghowizard55 at 61.64 and again at
25.00), a profile whose user no longer exists consumed a rank, and ranks were
numbered from the raw scan rather than from the rows that survived it.

The scoping is also a privacy property. A recruiter has no business being handed
a ranked directory of students' names and handles, and that is what an unscoped
board is.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ENDPOINT = (BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "users.py").read_text()


def _leaderboard_body() -> str:
    """The endpoint's source, to end of file when it is the last one defined."""
    start = ENDPOINT.index("async def get_leaderboard")
    end = ENDPOINT.find("\n@router", start)
    return ENDPOINT[start:] if end == -1 else ENDPOINT[start:end]


class TestTheBoardIsScoped(unittest.TestCase):
    def test_it_filters_by_account_type(self) -> None:
        body = _leaderboard_body()
        self.assertIn("scope_filter", body)
        self.assertIn("resolve_account_type", body)

    def test_it_no_longer_scans_every_profile(self) -> None:
        # The exact call that put four non-students on a students' board. The
        # string also appears in the comment explaining the bug, so this looks
        # for the call rather than the mention.
        self.assertNotIn("await Profile.find_all()", _leaderboard_body())
        self.assertIn("Profile.find(scope_filter)", _leaderboard_body())

    def test_it_uses_the_same_scope_helper_as_the_sidebar(self) -> None:
        # The two numbers sit on one screen. Sharing the helper is what stops
        # them describing different populations again.
        self.assertIn("_normalize_account_scope", ENDPOINT.split("async def _build_ranking_summary")[1][:400])


class TestScopeNormalisation(unittest.TestCase):
    """Whatever the board scopes to, it must be exactly one population."""

    def _scope(self, value):
        # The board scopes on the real account type, not the two-valued
        # candidate/employer shape the profile forms branch on - that one
        # collapses faculty and institution into "employer" and would rank a
        # professor against registrars.
        from app.core.account_types import resolve_account_type

        return resolve_account_type(value)

    def test_each_role_scopes_to_itself(self) -> None:
        for value in ("candidate", "employer", "faculty", "institution"):
            with self.subTest(value=value):
                self.assertEqual(self._scope(value), value)

    def test_an_unknown_role_does_not_widen_the_scope(self) -> None:
        # A scope that matched everything would put the whole user base back on
        # the board, which is the bug this file exists for.
        for value in (None, "", "   ", "nonsense", "admin"):
            with self.subTest(value=value):
                self.assertIn(
                    self._scope(value),
                    {"candidate", "employer", "faculty", "institution"},
                )


class TestOneRowPerPerson(unittest.TestCase):
    def test_the_endpoint_deduplicates_by_user(self) -> None:
        body = _leaderboard_body()
        self.assertIn("seen_users", body)

    def test_ranks_are_assigned_after_filtering(self) -> None:
        # Numbering from the raw scan meant a skipped row left a gap, so a board
        # could read #1, #2, #4 and every rank below a duplicate was wrong.
        body = _leaderboard_body()
        self.assertIn("rank=len(leaderboard) + 1", body)
        self.assertNotIn("for rank, profile in enumerate(profiles", body)

    def test_an_orphaned_profile_is_skipped(self) -> None:
        self.assertIn("if not user:", _leaderboard_body())


class TestTheNamesActuallyResolve(unittest.TestCase):
    """Source-text assertions cannot see a missing import.

    Every other test in this file reads the endpoint as a string, which is the
    right way to pin a query shape without a database - and it is blind to
    exactly one class of mistake. The import that brings `resolve_account_type`
    into this module was written into a trailing `# noqa` comment rather than
    into the import statement, so every string assertion passed and the live
    endpoint answered 500 with

        NameError: name 'resolve_account_type' is not defined

    These import the module and look the names up, which is the cheapest
    possible check that the file would survive being run.
    """

    def test_the_endpoint_module_imports(self) -> None:
        import app.api.api_v1.endpoints.users as endpoint

        self.assertTrue(hasattr(endpoint, "get_leaderboard"))

    def test_every_helper_the_endpoint_calls_is_bound(self) -> None:
        import app.api.api_v1.endpoints.users as endpoint

        for name in ("resolve_account_type", "percentile_of", "band_for", "ensure_system_username"):
            with self.subTest(name=name):
                self.assertTrue(
                    hasattr(endpoint, name),
                    f"{name} is called by get_leaderboard but is not bound in the module",
                )

    def test_no_import_was_written_into_a_comment(self) -> None:
        # The specific shape of the mistake: names appended after "# noqa".
        for line in ENDPOINT.splitlines():
            if "import" in line and "# noqa" in line:
                with self.subTest(line=line.strip()[:70]):
                    tail = line.split("# noqa", 1)[1]
                    self.assertNotIn(
                        "_", tail.replace("E402", "").replace("F401", ""),
                        "an import name looks like it was appended to a noqa comment",
                    )


class TestTheScanIsBounded(unittest.TestCase):
    def test_it_over_fetches_so_the_board_is_not_short(self) -> None:
        # Rows are dropped for orphans and duplicates, so scanning exactly the
        # limit returns fewer rows than asked for.
        body = _leaderboard_body()
        self.assertIn("scan_limit", body)
        self.assertIn("safe_limit * 3", body)

    def test_the_scan_still_has_a_ceiling(self) -> None:
        # It must not become the full-collection scan it replaced.
        body = _leaderboard_body()
        self.assertTrue("min(500" in body and "min(1000" in body)


if __name__ == "__main__":
    unittest.main()
