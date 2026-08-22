"""Grounding is enforced by the server, not requested in the prompt.

The generator used to ask the model to emit opportunity_id and url and then
checked them afterwards. llama-3.1-8b transcribing a 24-hex ObjectId produced
top_opportunity_id_not_retrieved:6a734a20c87526767b68e1cb and the whole answer
was discarded. The model now emits only a small integer ref and the server
resolves it, so an unretrieved citation is not a thing the model can express.
"""

from __future__ import annotations

import unittest

from app.services.rag_service import RAGService


CANDIDATES = [
    {"id": "aaa111", "url": "https://example.test/a", "title": "Alpha Internship"},
    {"id": "bbb222", "url": "https://example.test/b", "title": "Beta Hackathon"},
]


class ResolveRefsTests(unittest.TestCase):
    def test_valid_ref_resolves_to_canonical_id_url_and_title(self):
        parsed = {"top_opportunities": [{"ref": 1, "why_fit": "matches web3"}]}
        out = RAGService._resolve_refs(parsed, CANDIDATES)
        self.assertEqual(len(out["top_opportunities"]), 1)
        item = out["top_opportunities"][0]
        self.assertEqual(item["opportunity_id"], "bbb222")
        self.assertEqual(item["title"], "Beta Hackathon")
        self.assertEqual(item["citations"], [{"opportunity_id": "bbb222", "url": "https://example.test/b"}])
        self.assertNotIn("ref", item)

    def test_out_of_range_ref_is_dropped(self):
        parsed = {"top_opportunities": [{"ref": 7, "why_fit": "invented"}]}
        out = RAGService._resolve_refs(parsed, CANDIDATES)
        self.assertEqual(out["top_opportunities"], [])
        self.assertEqual(out["citations"], [])

    def test_non_integer_ref_is_dropped(self):
        parsed = {"top_opportunities": [{"ref": "6a734a20c87526767b68e1cb", "why_fit": "x"}]}
        out = RAGService._resolve_refs(parsed, CANDIDATES)
        self.assertEqual(out["top_opportunities"], [])

    def test_model_supplied_id_and_url_are_ignored(self):
        """The model cannot smuggle a citation past the resolver."""
        parsed = {
            "top_opportunities": [
                {"ref": 0, "opportunity_id": "deadbeef", "why_fit": "x",
                 "citations": [{"opportunity_id": "deadbeef", "url": "https://evil.test"}]}
            ],
            "citations": [{"opportunity_id": "deadbeef", "url": "https://evil.test"}],
        }
        out = RAGService._resolve_refs(parsed, CANDIDATES)
        item = out["top_opportunities"][0]
        self.assertEqual(item["opportunity_id"], "aaa111")
        self.assertEqual(item["citations"], [{"opportunity_id": "aaa111", "url": "https://example.test/a"}])
        self.assertEqual(out["citations"], [{"opportunity_id": "aaa111", "url": "https://example.test/a"}])

    def test_candidate_without_url_is_dropped(self):
        out = RAGService._resolve_refs(
            {"top_opportunities": [{"ref": 0, "why_fit": "x"}]},
            [{"id": "aaa111", "url": "", "title": "No URL"}],
        )
        self.assertEqual(out["top_opportunities"], [])

    def test_duplicate_refs_produce_one_citation(self):
        parsed = {"top_opportunities": [{"ref": 0, "why_fit": "a"}, {"ref": 0, "why_fit": "b"}]}
        out = RAGService._resolve_refs(parsed, CANDIDATES)
        self.assertEqual(len(out["top_opportunities"]), 2)
        self.assertEqual(len(out["citations"]), 1)


if __name__ == "__main__":
    unittest.main()
