import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.apify_unstop_client import charges_registration_fee, map_actor_item

# One real row as the actor returns it, captured from a live run.
LIVE_ROW = {
    "id": "1728532",
    "title": "Prasunethon 2.0",
    "opportunityType": "hackathons",
    "organizer": "Prasunet",
    "url": "https://unstop.com/hackathons/prasunethon-20-prasunet-1728532",
    "deadline": "2026-08-14T00:00:00+05:30",
    "deadlineText": "13 days left",
    "status": "live",
    "prize": "1: ₹50000 | 2: ₹25000",
    "registrationFee": "Free",
    "registrationCount": "33",
    "eligibility": "['Undergraduate', 'Postgraduate', 'Engineering Students']",
    "mode": "online",
    "location": "None",
    "tags": "['Artificial Intelligence (AI)', 'Python']",
}


class TestApifyUnstopMapping(unittest.TestCase):
    """Unstop's own markup yields a title and a link and little else.

    The managed actor returns a real deadline, structured eligibility and the
    registration fee - the three fields the corpus is most short of (deadline
    24% and largely synthetic, eligibility 23%, fee never captured at all).
    """

    def test_maps_the_fields_the_corpus_is_missing(self) -> None:
        mapped = map_actor_item(LIVE_ROW)
        assert mapped is not None
        self.assertEqual(mapped["opportunity_type"], "Hackathon")
        self.assertEqual(
            mapped["eligibility"], "Undergraduate, Postgraduate, Engineering Students"
        )
        self.assertEqual(mapped["work_mode"], "Remote")
        self.assertIsNotNone(mapped["deadline"])
        self.assertEqual(mapped["tags"], ["Artificial Intelligence (AI)", "Python"])

    def test_deadline_is_stored_naive_utc(self) -> None:
        """The scraper persists naive UTC; mixing tz-aware values here is what
        broke freshness metrics and killed ingestion for 40 days."""
        mapped = map_actor_item(LIVE_ROW)
        assert mapped is not None
        self.assertIsNone(mapped["deadline"].tzinfo)

    def test_liveness_is_a_real_observation(self) -> None:
        """Every other source records url_liveness_status "unknown"; Unstop
        actually reports whether the listing is still open."""
        self.assertEqual(map_actor_item(LIVE_ROW)["url_liveness_status"], "live")
        closed = dict(LIVE_ROW, status="closed")
        self.assertEqual(map_actor_item(closed)["url_liveness_status"], "unknown")

    def test_placeholder_eligibility_is_dropped(self) -> None:
        """Unstop writes ['All'] to mean "no restriction", which is not a signal."""
        row = dict(LIVE_ROW, eligibility="['All']")
        self.assertIsNone(map_actor_item(row)["eligibility"])

    def test_rows_without_a_title_or_url_are_skipped(self) -> None:
        self.assertIsNone(map_actor_item(dict(LIVE_ROW, title="")))
        self.assertIsNone(map_actor_item(dict(LIVE_ROW, url="")))

    def test_registration_fee_detection(self) -> None:
        """A paid registration is the strongest scam signal in this market, and
        it was never available to the trust service before."""
        for fee, expected in (
            ("Free", False),
            ("0", False),
            ("₹0", False),
            ("None", False),
            ("", False),
            ("₹499", True),
            ("Rs. 200", True),
            ("INR 1000", True),
        ):
            with self.subTest(fee=fee):
                self.assertEqual(charges_registration_fee({"registrationFee": fee}), expected)


if __name__ == "__main__":
    unittest.main()
