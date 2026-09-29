"""A declaration the generator does not understand must not vanish silently.

`generate_schema.py` promises a schema that is a function of the models. It
handled compound specs and pymongo IndexModels, and dropped plain strings - the
Beanie single-field shorthand, and 297 of the 383 declarations across these
models. Nothing failed; the indexes simply were not in the schema.

`vector_index_entries` is how it surfaced: the model declares three indexes and
the live table had none, which took a database query to notice. Measured there,
the missing index costs nothing today - the 100-id lookup the rebuild runs is a
sequential scan that executes in 1.5 ms on a table that fits in cache - so this
is not a performance fix. It is the generator telling the truth about the
models, before a table grows past the point where the planner can be casual.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "migrations" / "neon"))

from beanie import Document

from generate_schema import ddl_for  # noqa: E402


class StringIndexTests(unittest.TestCase):
    def _indexes(self, declared: list) -> list[str]:
        class Sample(Document):
            alpha: str = ""
            beta: int = 0

            class Settings:
                name = "samples"
                indexes = declared

        return ddl_for(Sample)[1]

    def test_a_string_declaration_becomes_an_index(self):
        indexes = self._indexes(["alpha"])
        self.assertEqual(len(indexes), 1)
        self.assertIn("ON app.samples (alpha ASC)", indexes[0])
        self.assertIn("CREATE INDEX IF NOT EXISTS", indexes[0])

    def test_a_leading_minus_is_descending(self):
        """Mongo's ordering shorthand; reading it as a column name would emit an
        index on a field that does not exist."""
        indexes = self._indexes(["-beta"])
        self.assertEqual(len(indexes), 1)
        self.assertIn("(beta DESC)", indexes[0])

    def test_a_field_the_model_does_not_have_is_skipped(self):
        """A stale declaration must not emit DDL that fails on apply."""
        self.assertEqual(self._indexes(["nonexistent"]), [])

    def test_compound_declarations_still_work(self):
        indexes = self._indexes([[("alpha", 1), ("beta", -1)]])
        self.assertEqual(len(indexes), 1)
        self.assertIn("(alpha ASC, beta DESC)", indexes[0])

    def test_every_shape_together(self):
        self.assertEqual(len(self._indexes(["alpha", "-beta", [("alpha", 1), ("beta", 1)]])), 3)


class GeneratedSchemaTests(unittest.TestCase):
    """Guards the checked-in file, not just the function that writes it."""

    def setUp(self):
        self.sql = (BACKEND_ROOT / "migrations" / "neon" / "002_generated_schema.sql").read_text()

    def test_the_table_that_exposed_this_has_its_declared_indexes(self):
        for column in ("opportunity_id", "text_hash", "updated_at"):
            self.assertIn(
                f"CREATE INDEX IF NOT EXISTS vector_index_entries_{column}_idx",
                self.sql,
                f"{column} missing - regenerate with migrations/neon/generate_schema.py",
            )

    def test_the_file_is_still_idempotent(self):
        """It is re-run against existing databases, so every statement has to be
        safe to apply twice."""
        for statement in self.sql.splitlines():
            if statement.startswith("CREATE INDEX"):
                self.assertIn("IF NOT EXISTS", statement)
            if statement.startswith("CREATE TABLE"):
                self.assertIn("IF NOT EXISTS", statement)


if __name__ == "__main__":
    unittest.main()
