"""jsonb columns must persist nested Pydantic models as JSON objects.

Regression: coerce_for_column passed jsonb values straight to the connection's
json codec, whose serializer falls back to str() for unknown objects. A
list[ExperimentVariant] persisted as its repr, reloaded as a str, and every
`v.name for v in experiment.variants` raised AttributeError inside
ensure_defaults() - which main.py catches and prints, so the RAG template
registry silently failed to initialise on every boot.
"""

from __future__ import annotations

import json
import unittest

from app.db.pg_odm import coerce_for_column
from app.models.experiment import ExperimentVariant


class NestedModelSerializationTests(unittest.TestCase):
    def test_nested_model_list_becomes_json_objects(self):
        value = [ExperimentVariant(name="ask_ai.v2", weight=1.0, is_control=True)]
        out = coerce_for_column(value, "jsonb")
        self.assertIsInstance(out[0], dict)
        self.assertEqual(out[0]["name"], "ask_ai.v2")

    def test_result_is_json_serialisable(self):
        """What the codec will actually attempt. str() output would pass this too,
        so the dict assertion above is the one that pins the behaviour."""
        value = [ExperimentVariant(name="ask_ai.v2", weight=1.0, is_control=True)]
        json.dumps(coerce_for_column(value, "jsonb"))

    def test_nested_model_inside_a_mapping(self):
        value = {"variants": [ExperimentVariant(name="v1", weight=1.0, is_control=True)]}
        out = coerce_for_column(value, "jsonb")
        self.assertIsInstance(out["variants"][0], dict)
        self.assertEqual(out["variants"][0]["name"], "v1")

    def test_plain_payloads_are_returned_unchanged(self):
        """The codec handles these already; the fix must not reshape them."""
        for payload in ({"a": [1, 2], "b": "x"}, [1, "two", None], {"nested": {"k": [True]}}):
            self.assertEqual(coerce_for_column(payload, "jsonb"), payload)

    def test_none_stays_none(self):
        self.assertIsNone(coerce_for_column(None, "jsonb"))


if __name__ == "__main__":
    unittest.main()
