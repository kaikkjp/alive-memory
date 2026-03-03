"""Metric: NDCG — Normalized Discounted Cumulative Gain for ranking quality."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from benchmarks.runner import BenchmarkResult


@dataclass
class NDCGResult:
    """Ranking quality metrics."""

    ndcg_at_5: float
    ndcg_at_3: float
    ndcg_by_category: dict[str, float] = field(default_factory=dict)
    mrr: float = 0.0


def _dcg(relevances: list[bool], k: int) -> float:
    """Compute Discounted Cumulative Gain at k."""
    dcg = 0.0
    for i in range(min(k, len(relevances))):
        rel = 1.0 if relevances[i] else 0.0
        dcg += rel / math.log2(i + 2)  # i+2 because log2(1) = 0
    return dcg


def _ndcg_at_k(relevances: list[bool], k: int) -> float:
    """Compute NDCG@k for a single query's relevance vector."""
    if not relevances:
        return 0.0

    dcg = _dcg(relevances, k)

    # Ideal: all relevant results first
    ideal = sorted(relevances, reverse=True)
    idcg = _dcg(ideal, k)

    if idcg == 0.0:
        return 0.0 if any(relevances) else 1.0  # no relevant docs = perfect if nothing expected
    return dcg / idcg


def compute_ndcg(result: BenchmarkResult) -> NDCGResult:
    """Compute NDCG ranking quality from a benchmark result."""
    if not result.final_metrics or not result.final_metrics.recall_scores:
        return NDCGResult(ndcg_at_5=0.0, ndcg_at_3=0.0)

    scores = result.final_metrics.recall_scores
    ndcg5_values = []
    ndcg3_values = []
    by_category: dict[str, list[float]] = {}
    mrr_values = []

    for scored in scores:
        vec = scored.relevance_vector
        if not vec:
            continue

        n5 = _ndcg_at_k(vec, 5)
        n3 = _ndcg_at_k(vec, 3)
        ndcg5_values.append(n5)
        ndcg3_values.append(n3)

        by_category.setdefault(scored.category, []).append(n5)
        mrr_values.append(scored.mrr)

    if not ndcg5_values:
        return NDCGResult(ndcg_at_5=0.0, ndcg_at_3=0.0)

    return NDCGResult(
        ndcg_at_5=sum(ndcg5_values) / len(ndcg5_values),
        ndcg_at_3=sum(ndcg3_values) / len(ndcg3_values),
        ndcg_by_category={
            cat: sum(vals) / len(vals) for cat, vals in by_category.items()
        },
        mrr=sum(mrr_values) / len(mrr_values) if mrr_values else 0.0,
    )
