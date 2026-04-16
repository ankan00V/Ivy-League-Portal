from __future__ import annotations

import math
from typing import Iterable


def precision_at_k(predicted_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    topk = predicted_ids[:k]
    if not topk:
        return 0.0
    hits = sum(1 for item in topk if item in relevant_ids)
    return hits / float(k)


def recall_at_k(predicted_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    topk = predicted_ids[:k]
    hits = sum(1 for item in topk if item in relevant_ids)
    return hits / float(len(relevant_ids))


def ndcg_at_k(predicted_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    if not relevant_ids:
        return 0.0

    safe_k = min(k, len(predicted_ids))
    if safe_k <= 0:
        return 0.0

    dcg = 0.0
    for rank, item_id in enumerate(predicted_ids[:safe_k], start=1):
        rel = 1.0 if item_id in relevant_ids else 0.0
        if rel <= 0.0:
            continue
        dcg += rel / math.log2(rank + 1.0)

    ideal_hits = min(len(relevant_ids), safe_k)
    if ideal_hits <= 0:
        return 0.0
    idcg = sum(1.0 / math.log2(rank + 1.0) for rank in range(1, ideal_hits + 1))
    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


def mrr(predicted_ids: list[str], relevant_ids: set[str], k: int | None = None) -> float:
    if not relevant_ids:
        return 0.0
    scan = predicted_ids if k is None else predicted_ids[: max(0, k)]
    for idx, item_id in enumerate(scan, start=1):
        if item_id in relevant_ids:
            return 1.0 / float(idx)
    return 0.0


def normalize_relevant_ids(relevant_ids: Iterable[str]) -> set[str]:
    return {str(value) for value in relevant_ids if value}

