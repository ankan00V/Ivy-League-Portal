"""An inferred constraint must not be able to delete the corpus.

`_passes_filters` applies the classifier's intent as a hard filter. Location,
work mode and opportunity type come from the student's own words; intent does
not - it is guessed, and measured on app/data/intent_queries.json it is wrong on
6 of 40 queries, every miss reading an internship question as "research".

A hard filter turns that miss into deletion rather than degradation: only 59 of
203 Bangalore listings carry research/fellowship/assistant, so "data science
internships in Bangalore" was answered from a quarter of the city's rows and
came back empty.

Gating on confidence does not work - wrong labels scored 0.67-0.75 against
correct ones at 0.70-0.84 - so the outcome decides instead: a filtered pass that
cannot fill the page drops the inferred constraint and keeps the stated ones.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.vector_service import OpportunityVectorService


def _meta(title: str, description: str = "", location: str = "") -> dict:
    return {
        "id": title.lower().replace(" ", "-"),
        "url": f"https://example.com/{title.lower().replace(' ', '-')}",
        "title": title,
        "description": description,
        "location": location,
        "university": "",
        "opportunity_type": "Internship",
    }


class IntentFilterFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = OpportunityVectorService()
        # Five Bangalore internships, none of which uses a "research" word: the
        # shape of the real corpus, where 144 of 203 Bangalore rows are like this.
        self.service._metas = [
            _meta("Data Science Internship", "python sql", "Bangalore"),
            _meta("ML Engineering Internship", "pytorch", "Bangalore"),
            _meta("Analytics Internship", "dashboards", "Bangalore"),
            _meta("Backend Internship", "fastapi", "Bangalore"),
            _meta("Research Assistant", "nlp lab", "Bangalore"),
        ]
        dim = 4
        self.service._vectors = np.tile(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), (5, 1))
        # Descending similarity so ordering is deterministic.
        for row in range(5):
            self.service._vectors[row] = np.array([1.0 - row * 0.01, 0.0, 0.0, 0.0], dtype=np.float32)
        self.service._index = None
        self.query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        self.dim = dim

    async def _search(self, filters, top_k=4):
        with patch.object(self.service, "_ensure_index", return_value=None):
            return await self.service.search_by_vector(self.query, top_k=top_k, filters=filters)

    async def test_a_wrong_intent_no_longer_empties_the_page(self):
        """The reported failure: an internships query labelled "research"."""
        results = await self._search({"intent": "research", "locations": ["Bangalore"]})
        self.assertEqual(len(results), 4)

    async def test_the_stated_constraints_still_apply_after_relaxing(self):
        """Dropping the guess must not drop the student's own words."""
        self.service._metas[0]["location"] = "Chennai"
        self.service._metas[0]["description"] = "python sql"
        results = await self._search({"intent": "research", "locations": ["Bangalore"]})
        self.assertTrue(results)
        for item in results:
            self.assertNotIn("chennai", item["location"].lower())

    async def test_a_correct_intent_that_fills_the_page_is_untouched(self):
        """When the classifier is right the page is already full, so nothing
        relaxes and the precision of the filter is kept."""
        results = await self._search({"intent": "internships"}, top_k=4)
        self.assertEqual(len(results), 4)
        self.assertNotIn("Research Assistant", [item["title"] for item in results])

    async def test_relaxing_only_happens_when_it_finds_more(self):
        """A genuinely empty corpus must stay empty rather than be padded."""
        results = await self._search({"intent": "research", "locations": ["Reykjavik"]})
        self.assertEqual(results, [])

    async def test_intent_is_the_only_filter_relaxed(self):
        """Work mode and type are stated, not inferred; they are not negotiable."""
        results = await self._search(
            {"intent": "research", "opportunity_types": ["scholarship"]}, top_k=4
        )
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
