"""The summary must describe the candidates, not echo the query's constraints.

Asked for "data science internships in Bangalore" against a corpus holding no
active data science role in Bangalore, the generator answered "Found 2 data
science internships in Bangalore" over two rows that were neither. Retrieval was
not at fault - it returned its nearest neighbours, which is all it can do - and
the shortlist itself was defensible. The summary was not: it restated the query
as though the corpus had confirmed it, which is the one sentence a reader takes
at face value.

The rule lives in the stored template, so a wording fix only reaches a running
deployment when SYSTEM_PROMPT_SCHEMA_VERSION is bumped alongside it. Both halves
are pinned here because either one alone is a no-op.
"""

from __future__ import annotations

import unittest

from app.services.rag_template_registry_service import (
    SYSTEM_PROMPT_SCHEMA_VERSION,
    _default_system_prompt,
)


class SummaryRulesTests(unittest.TestCase):
    def test_summary_is_bound_to_the_candidates_not_the_query(self):
        """Without this rule the model narrates the query back as a finding."""
        prompt = _default_system_prompt().lower()
        self.assertIn("summary must describe what the candidates below actually are", prompt)
        self.assertIn("never what the query asked for", prompt)

    def test_prompt_names_the_constraints_that_get_echoed(self):
        """"Data science" and "Bangalore" were both the query's words, not the
        rows'. Naming the categories is what makes the rule checkable by the
        model; a general plea for accuracy did not survive contact with it."""
        prompt = _default_system_prompt().lower()
        for constraint in ("role", "domain", "location", "opportunity type"):
            self.assertIn(constraint, prompt)

    def test_a_missed_constraint_must_be_stated_rather_than_glossed(self):
        """Abstention handles "nothing is close". This covers the other case:
        rows worth showing that still do not meet what was asked for."""
        prompt = _default_system_prompt().lower()
        self.assertIn("no candidate meets a constraint the query stated", prompt)
        self.assertIn("describe what was found instead", prompt)


class SchemaVersionRolloutTests(unittest.TestCase):
    def test_version_is_at_least_the_release_that_added_the_summary_rules(self):
        """ensure_defaults() only supersedes a stored row when this number is
        above the one recorded on it. Editing the prompt without raising this
        leaves every seeded deployment - including production - on the old
        text, with the fix visible in the diff and absent from the answers."""
        self.assertGreaterEqual(SYSTEM_PROMPT_SCHEMA_VERSION, 3)


if __name__ == "__main__":
    unittest.main()
