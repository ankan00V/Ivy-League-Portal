"""The embedding pass must not write one row per round trip.

embed_opportunities awaited row.save() inside its per-row loop. A forced pass
over the corpus was one sequential round trip per opportunity - ~2,400 of them
against Supabase - which on its own exceeded the 900s deadline the job runs
under. embeddings.rebuild died at that deadline 93 consecutive times, and
because the writes were never committed as a group the next run redid all of it.

bulk_save already existed for precisely this bug (the vector index rebuild had
it first); this caller was simply never moved onto it. The regression has no
visible symptom other than elapsed time, so it gets a test that counts writes
rather than measuring seconds.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import embedding_pipeline as ep_mod


class _Row:
    def __init__(self, idx: int) -> None:
        self.id = idx
        self.title = f"role {idx}"
        self.description = "d"
        self.embedding = None
        self.embedding_text_hash = None
        self.embedding_model_version = None
        self.embedding_updated_at = None
        self.updated_at = None
        self.saved = 0

    async def save(self):
        self.saved += 1


class TestEmbeddingPassBatchesItsWrites(unittest.IsolatedAsyncioTestCase):
    async def _run(self, rows, batch_size=64):
        calls = []

        async def fake_save_rows(batch):
            calls.append(len(batch))
            return len(batch)

        async def fake_embed(texts):
            return np.ones((len(texts), 4), dtype=np.float32)

        class _Q:
            def sort(self, *_a):
                return self

            def limit(self, *_a):
                return self

            async def to_list(self):
                return rows

        with (
            patch.object(ep_mod, "_save_rows", fake_save_rows),
            patch.object(ep_mod.Opportunity, "find_many", lambda *a, **k: _Q()),
            patch.object(ep_mod.embedding_service, "embed_texts", fake_embed),
            patch.object(ep_mod.settings, "EMBEDDING_BATCH_SIZE", batch_size),
        ):
            report = await ep_mod.embedding_pipeline.embed_opportunities(force=True)
        return report, calls

    async def test_writes_are_batched_not_per_row(self) -> None:
        rows = [_Row(i) for i in range(150)]
        report, calls = await self._run(rows, batch_size=64)

        self.assertEqual(report.updated, 150)
        # 150 rows at 64 per batch is three writes, not 150.
        self.assertEqual(calls, [64, 64, 22])
        self.assertTrue(
            all(r.saved == 0 for r in rows), "no row may be saved individually"
        )

    async def test_every_row_still_gets_its_embedding_fields(self) -> None:
        # Batching must not skip the field assignment it replaced.
        rows = [_Row(i) for i in range(10)]
        await self._run(rows, batch_size=4)
        for row in rows:
            self.assertIsNotNone(row.embedding)
            self.assertIsNotNone(row.embedding_text_hash)
            self.assertEqual(row.embedding_model_version, ep_mod.embedding_pipeline.model_version)

    async def test_partial_progress_is_committed_per_batch(self) -> None:
        # The point of batching here: a run killed by the deadline keeps what it
        # finished rather than discarding the whole pass.
        rows = [_Row(i) for i in range(10)]
        landed = []

        async def failing_save(batch):
            if len(landed) >= 4:
                raise TimeoutError("deadline")
            landed.extend(batch)
            return len(batch)

        async def fake_embed(texts):
            return np.ones((len(texts), 4), dtype=np.float32)

        class _Q:
            def sort(self, *_a):
                return self

            def limit(self, *_a):
                return self

            async def to_list(self):
                return rows

        with (
            patch.object(ep_mod, "_save_rows", failing_save),
            patch.object(ep_mod.Opportunity, "find_many", lambda *a, **k: _Q()),
            patch.object(ep_mod.embedding_service, "embed_texts", fake_embed),
            patch.object(ep_mod.settings, "EMBEDDING_BATCH_SIZE", 4),
        ):
            with self.assertRaises(TimeoutError):
                await ep_mod.embedding_pipeline.embed_opportunities(force=True)

        # First batch of 4 committed; the second raised. What landed, stayed.
        self.assertEqual(len(landed), 4, "committed batches must survive the failure")


if __name__ == "__main__":
    unittest.main()
