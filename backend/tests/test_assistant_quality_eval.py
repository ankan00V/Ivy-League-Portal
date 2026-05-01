import unittest

from benchmarks.run_assistant_quality_eval import _evaluate


class TestAssistantQualityEval(unittest.TestCase):
    def test_route_precision_uses_golden_expected_tools(self) -> None:
        payload = _evaluate(
            [
                {
                    "input": "Show my profile skills and resume gaps.",
                    "expected_mode": "tool",
                    "expected_tool": "profile_lookup",
                },
                {
                    "input": "Why was this ranked first?",
                    "expected_mode": "tool",
                    "expected_tool": "ranking_explanation",
                },
            ],
            prompt_version="assistant.test",
        )

        self.assertEqual(payload["dataset_size"], 2)
        self.assertEqual(payload["metrics"]["tool_route_precision"], 1.0)
        self.assertEqual(payload["metrics"]["expected_tool_precision"], 1.0)


if __name__ == "__main__":
    unittest.main()
