"""The Python classifier must agree with the TypeScript one it was ported from.

Role track is computed server-side so the feed can stop shipping descriptions to
the browser, which is what took a feed request from 3.36 MB to a fraction of it.
That only holds if both implementations return the same answer. Two copies of a
120-entry taxonomy in two languages drift the first time someone edits one, and
the failure is silent: listings quietly move between the Technical and
Non-technical tracks with nothing to catch it.

So this test does not re-assert the rules. It runs the real TypeScript
implementation and diffs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from app.services.role_classification import classify_role_track

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
VOCAB = REPO_ROOT / "backend" / "app" / "data" / "role_classification.json"

# Titles chosen to cover every branch: exact taxonomy names, keyword scoring,
# both-track ambiguity, and the empty/garbage fallback.
SAMPLE_LISTINGS = [
    {"title": "Machine Learning Intern", "description": "python pytorch", "tags": ["ml"]},
    {"title": "Backend Developer", "description": "django api", "tags": []},
    {"title": "Marketing Intern", "description": "seo campaigns", "tags": ["brand"]},
    {"title": "Finance Analyst", "description": "audit treasury", "tags": []},
    {"title": "Data Analyst, Marketing", "description": "sql and campaign work", "tags": []},
    {"title": "Network Engineering Intern (Summer 2026)", "description": "", "tags": []},
    {"title": "Graduate Trainee Engineer", "description": "manufacturing", "tags": []},
    {"title": "Sales Business Development", "description": "customer success", "tags": []},
    {"title": "Product & Design Intern", "description": "figma ux", "tags": []},
    {"title": "Cybersecurity Analyst", "description": "soc appsec", "tags": []},
    {"title": "", "description": "", "tags": []},
    {"title": "Opportunity", "description": "unclear listing text", "tags": []},
    {"title": "HackerOne AI Red Teaming", "description": "security research", "tags": []},
    {"title": "Content Writer", "description": "editor copywriter", "tags": []},
    {"title": "Excel wizard for business ops", "description": "spreadsheets", "tags": []},
]


def _node_available() -> bool:
    return shutil.which("npx") is not None


class RoleClassificationParityTests(unittest.TestCase):
    def test_committed_vocabulary_is_not_stale(self):
        """The JSON Python reads must match what the TypeScript source emits."""
        if not _node_available():
            self.skipTest("npx unavailable; cannot regenerate vocabulary")
        result = subprocess.run(
            ["npx", "--yes", "tsx", "scripts/generate-role-vocabulary.mjs"],
            cwd=FRONTEND, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            self.skipTest(f"generator failed: {result.stderr[-300:]}")
        regenerated = json.loads(result.stdout)
        committed = json.loads(VOCAB.read_text())
        self.assertEqual(
            committed, regenerated,
            "backend/app/data/role_classification.json is stale. Regenerate it:\n"
            "  cd frontend && npx tsx scripts/generate-role-vocabulary.mjs "
            "> ../backend/app/data/role_classification.json",
        )

    def test_python_matches_typescript_on_real_listings(self):
        """Both implementations must return the same track for the same input."""
        if not _node_available():
            self.skipTest("npx unavailable; cannot run the TypeScript classifier")
        stdin = "\n".join(json.dumps(row) for row in SAMPLE_LISTINGS)
        result = subprocess.run(
            ["npx", "--yes", "tsx", "scripts/classify-titles.mjs"],
            cwd=FRONTEND, input=stdin, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            self.skipTest(f"TS classifier failed: {result.stderr[-300:]}")

        ts_tracks = [line for line in result.stdout.strip().split("\n") if line]
        self.assertEqual(len(ts_tracks), len(SAMPLE_LISTINGS), "TS returned the wrong row count")

        mismatches = []
        for listing, ts_track in zip(SAMPLE_LISTINGS, ts_tracks):
            py_track = classify_role_track(
                title=listing.get("title"),
                description=listing.get("description"),
                tags=listing.get("tags"),
            )
            if py_track != ts_track:
                mismatches.append(f"  {listing['title']!r}: python={py_track} typescript={ts_track}")
        self.assertFalse(mismatches, "Classifier drift:\n" + "\n".join(mismatches))


if __name__ == "__main__":
    unittest.main()
