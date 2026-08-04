"""Greenhouse boards are discovered, not curated.

A hardcoded company list decides in advance which employers students can see.
Greenhouse has no list-all-boards endpoint - a board is addressed by its own
company token - so the corpus itself is the directory: every Greenhouse job URL
already carries the employer's token. Any Greenhouse-hosted company the scraper
meets through any other source therefore gets its board read on the next run,
without anyone naming it.
"""
from __future__ import annotations

from app.services.scraper import (
    GREENHOUSE_BOOTSTRAP_BOARD_TOKENS,
    discover_greenhouse_board_tokens,
)


class TestBoardTokenDiscovery:
    def test_recognises_every_greenhouse_url_shape(self):
        found = discover_greenhouse_board_tokens([
            "https://boards.greenhouse.io/razorpay/jobs/123",
            "https://job-boards.greenhouse.io/postman/jobs/9",
            "https://boards-api.greenhouse.io/v1/boards/cred/jobs",
            "https://boards.greenhouse.io/embed/job_board?for=sprinklr",
        ])
        assert set(found) == {"razorpay", "postman", "cred", "sprinklr"}

    def test_ignores_non_greenhouse_urls(self):
        assert discover_greenhouse_board_tokens([
            "https://example.com/careers",
            "https://lever.co/acme",
            "",
        ]) == []

    def test_drops_path_segments_that_are_not_companies(self):
        found = discover_greenhouse_board_tokens([
            "https://boards-api.greenhouse.io/v1/boards/",
            "https://boards.greenhouse.io/embed/",
        ])
        for stopword in ("v1", "embed", "boards", "jobs"):
            assert stopword not in found

    def test_deduplicates_and_normalises_case(self):
        found = discover_greenhouse_board_tokens([
            "https://boards.greenhouse.io/Razorpay/jobs/1",
            "https://boards.greenhouse.io/razorpay/jobs/2",
        ])
        assert found == ["razorpay"]

    def test_bootstrap_list_is_only_a_cold_start_seed(self):
        """It exists for an empty database, so it must stay small.

        A long curated list would quietly become the real source of truth again
        and reintroduce the fairness problem discovery is meant to solve.
        """
        assert len(GREENHOUSE_BOOTSTRAP_BOARD_TOKENS) <= 3, (
            "the bootstrap seed is growing into a curated allowlist; boards "
            "should be discovered from the corpus instead"
        )
