"""Metric 2: Temporal Coherence — does the system understand time ordering?"""

from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class TemporalCoherenceResult:
    ordering_accuracy: float  # correct before/after judgments
    recency_bias_score: float  # over-weight recent? under-weight old?
    temporal_precision: float  # distinguish "yesterday" from "last week"?


def compute_temporal_coherence(result: BenchmarkResult) -> TemporalCoherenceResult:
    """Compute temporal coherence from benchmark results.

    Extracts temporal_ordering, temporal_distance, and recency category scores.
    """
    if not result.final_metrics:
        return TemporalCoherenceResult(0, 0, 0)

    by_cat = result.final_metrics.recall_by_category

    ordering = by_cat.get("temporal_ordering", {}).get("f1", 0.0)
    temporal_distance = by_cat.get("temporal_distance", {}).get("f1", 0.0)

    # Recency bias: compare temporal_distance score to basic_recall.
    # If temporal_distance is much lower, system has recency bias.
    basic = by_cat.get("basic_recall", {}).get("f1", 0.0)
    if basic > 0:
        recency_bias = 1.0 - max(0, basic - temporal_distance)
    else:
        recency_bias = 0.5  # can't tell

    return TemporalCoherenceResult(
        ordering_accuracy=ordering,
        recency_bias_score=recency_bias,
        temporal_precision=temporal_distance,
    )
