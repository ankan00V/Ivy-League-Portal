import unittest
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.mlops.activation_policy import evaluate_activation_policy


class TestActivationPolicy(unittest.TestCase):
    def test_manual_policy_never_auto_activates(self) -> None:
        decision = evaluate_activation_policy(
            auto_activate=True,
            policy="manual",
            auc_gain=0.08,
            min_auc_gain=0.02,
            positive_rate=0.15,
            min_positive_rate=0.01,
            learned_weights={"semantic": 0.6, "baseline": 0.25, "behavior": 0.15},
            baseline_weights={"semantic": 0.55, "baseline": 0.3, "behavior": 0.15},
            max_weight_shift=0.5,
            require_online_kpis=False,
        )
        self.assertFalse(decision.should_activate)
        self.assertEqual(decision.policy, "manual")
        self.assertEqual(decision.reason, "manual_policy_requires_explicit_activation")

    def test_guarded_policy_blocks_large_weight_shift(self) -> None:
        decision = evaluate_activation_policy(
            auto_activate=True,
            policy="guarded",
            auc_gain=0.06,
            min_auc_gain=0.01,
            positive_rate=0.09,
            min_positive_rate=0.02,
            learned_weights={"semantic": 0.95, "baseline": 0.03, "behavior": 0.02},
            baseline_weights={"semantic": 0.55, "baseline": 0.3, "behavior": 0.15},
            max_weight_shift=0.2,
            require_online_kpis=False,
        )
        self.assertFalse(decision.should_activate)
        self.assertTrue(decision.reason.startswith("weight_shift_above_threshold"))

    def test_auc_gain_policy_activates_when_thresholds_pass(self) -> None:
        decision = evaluate_activation_policy(
            auto_activate=True,
            policy="auc_gain",
            auc_gain=0.03,
            min_auc_gain=0.01,
            positive_rate=0.08,
            min_positive_rate=0.01,
            learned_weights={"semantic": 0.58, "baseline": 0.28, "behavior": 0.14},
            baseline_weights={"semantic": 0.55, "baseline": 0.3, "behavior": 0.15},
            max_weight_shift=0.35,
            guardrail_report={"data_complete": True, "deltas": {"ctr": 0.0}},
            require_online_kpis=False,
        )
        self.assertTrue(decision.should_activate)
        self.assertEqual(decision.reason, "activated")

    def test_guarded_policy_blocks_when_online_guardrail_data_missing(self) -> None:
        decision = evaluate_activation_policy(
            auto_activate=True,
            policy="guarded",
            auc_gain=0.05,
            min_auc_gain=0.01,
            positive_rate=0.09,
            min_positive_rate=0.01,
            learned_weights={"semantic": 0.58, "baseline": 0.28, "behavior": 0.14},
            baseline_weights={"semantic": 0.55, "baseline": 0.3, "behavior": 0.15},
            max_weight_shift=0.35,
            guardrail_report={"data_complete": False, "deltas": {}},
            require_online_kpis=True,
        )
        self.assertFalse(decision.should_activate)
        self.assertEqual(decision.reason, "guardrail_data_missing")

    def test_guarded_policy_blocks_ctr_lift_with_apply_rate_regression(self) -> None:
        decision = evaluate_activation_policy(
            auto_activate=True,
            policy="guarded",
            auc_gain=0.05,
            min_auc_gain=0.01,
            positive_rate=0.09,
            min_positive_rate=0.01,
            learned_weights={"semantic": 0.58, "baseline": 0.28, "behavior": 0.14},
            baseline_weights={"semantic": 0.55, "baseline": 0.3, "behavior": 0.15},
            max_weight_shift=0.35,
            guardrail_report={
                "data_complete": True,
                "deltas": {
                    "ctr": 0.02,
                    "apply_rate": -0.01,
                    "freshness_seconds": 0.0,
                    "latency_p95_ms": 0.0,
                    "failure_rate": 0.0,
                },
            },
            require_online_kpis=True,
            max_apply_rate_drop=0.0,
        )
        self.assertFalse(decision.should_activate)
        self.assertTrue(decision.reason.startswith("guardrail_apply_rate_regression"))


if __name__ == "__main__":
    unittest.main()
