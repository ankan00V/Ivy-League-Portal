"""Repeat impressions of the same card collapse inside a window.

Every feed render used to write one row per visible listing. Measured on Supabase
2026-08-11: 30,143 impression rows covered only 1,318 distinct
(user, opportunity) pairs — 22.9x duplication, with a single card logged 42 times
to one user, each row carrying a ~1 KB feature payload. That was adding roughly
6.7 MB/day to a 500 MB tier, from two developer accounts.

The dedup is also the more honest measurement. Counting a card 42 times because a
student scrolled past it inflates the CTR denominator, which makes the ranker look
worse than it is.

The invariant that must never break: **only impressions collapse.** A click, save
or apply is a deliberate act and always writes.
"""
from __future__ import annotations

import inspect

from app.core.config import settings
from app.services.interaction_service import InteractionService, interaction_service


class TestDedupConfiguration:
    def test_window_is_configurable_and_disableable(self):
        assert hasattr(settings, "IMPRESSION_DEDUP_WINDOW_MINUTES")
        assert isinstance(settings.IMPRESSION_DEDUP_WINDOW_MINUTES, int)

    def test_window_is_on_by_default(self):
        assert settings.IMPRESSION_DEDUP_WINDOW_MINUTES > 0


class TestOnlyImpressionsCollapse:
    def test_dedup_lives_in_the_impression_path_only(self):
        """log_event is the shared writer; putting dedup there would eat clicks."""
        event_source = inspect.getsource(InteractionService.log_event)
        assert "IMPRESSION_DEDUP_WINDOW_MINUTES" not in event_source
        assert "already_seen" not in event_source

    def test_impression_path_applies_the_window(self):
        source = inspect.getsource(InteractionService.log_impressions)
        assert "IMPRESSION_DEDUP_WINDOW_MINUTES" in source
        assert "already_seen" in source

    def test_lookup_filters_to_impressions(self):
        """A click must not suppress a later impression of the same card."""
        source = inspect.getsource(InteractionService._recently_impressed)
        assert 'interaction_type == "impression"' in source


class TestQueryShape:
    def test_lookup_is_one_query_per_batch_not_per_card(self):
        """A feed render posts every visible listing; per-card checks would be N round trips."""
        source = inspect.getsource(InteractionService.log_impressions)
        loop_at = source.index("for impression in impressions")
        lookup_at = source.index("_recently_impressed")
        assert lookup_at < loop_at, "the recent-impression lookup must happen before the loop"

    def test_lookup_fails_open(self):
        """A dedup lookup failure must cost a duplicate row, never a lost measurement."""
        source = inspect.getsource(InteractionService._recently_impressed)
        assert "except Exception" in source
        assert "return set()" in source

    def test_disabled_window_short_circuits(self):
        source = inspect.getsource(InteractionService._recently_impressed)
        assert "window_minutes <= 0" in source


class TestWithinBatchCollapse:
    def test_a_card_repeated_in_one_payload_is_written_once(self):
        """Guards the `already_seen.add` that handles duplicates inside a render."""
        source = inspect.getsource(InteractionService.log_impressions)
        assert "already_seen.add" in source


class TestServiceSingleton:
    def test_singleton_exposes_the_new_helper(self):
        assert hasattr(interaction_service, "_recently_impressed")
        assert hasattr(interaction_service, "log_impressions")
