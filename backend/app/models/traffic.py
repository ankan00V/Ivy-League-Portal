"""Traffic provenance: telling real student activity apart from seeded activity.

Every ranking metric in this repo is only meaningful if it can answer "did a real
person do this?". `bootstrap_ranking_pipeline.py` writes impressions, clicks, saves
and applies from hardcoded probabilities so the ranker has something to train on,
and those rows live in the same collections as genuine traffic.

The discriminator is `traffic_type`. Rows carry "real" or "simulated".

**A missing or blank `traffic_type` is NOT real.** It is unknown provenance, and the
filters below exclude it from real-traffic queries.

This is deliberate and it is a reversal. Three call sites previously treated blank
as real for backward compatibility, which meant every seeded row written before the
field existed was counted as genuine student activity. The published
`real_traffic_rollout_readiness` gate reported 260 "real" impressions and a +13.8pp
CTR win for the `ml` ranker on that basis, while actual non-seed traffic was 1,402
impressions and zero clicks.

Release gates must fail closed. Under-counting real traffic delays a promotion;
over-counting it promotes a model on evidence that does not exist.
"""

from typing import Any, Literal


TrafficType = Literal["real", "simulated"]

TrafficTypeFilter = Literal["all", "real", "simulated"]


def normalize_traffic_type(value: str | None) -> str:
    """Lower-case and strip a stored traffic_type. Missing becomes ""."""
    return (value or "").strip().lower()


def matches_traffic_type(value: str | None, traffic_type: str) -> bool:
    """In-Python predicate for a single row.

    Mirrors `traffic_type_query` exactly - if you change one, change both, and the
    parity is asserted in tests/test_traffic_provenance.py.
    """
    normalized_filter = (traffic_type or "all").strip().lower()
    if normalized_filter == "all":
        return True
    normalized_value = normalize_traffic_type(value)
    if normalized_filter == "real":
        return normalized_value == "real"
    if normalized_filter == "simulated":
        return normalized_value == "simulated"
    return False


def traffic_type_query(traffic_type: str) -> dict[str, Any]:
    """MongoDB filter fragment for the same rule.

    Returns {} for "all" so it can be spread into a larger match stage.
    """
    normalized_filter = (traffic_type or "all").strip().lower()
    if normalized_filter == "all":
        return {}
    if normalized_filter in {"real", "simulated"}:
        return {"traffic_type": normalized_filter}
    return {"traffic_type": "__no_such_traffic_type__"}
