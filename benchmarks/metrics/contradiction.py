"""Metric 3: Contradiction Handling — does the system return current facts?"""

from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class ContradictionResult:
    update_accuracy: float  # returns updated fact, not stale
    stale_rate: float  # how often outdated info returned
    dual_return_rate: float  # returns BOTH old and new
    correction_latency_cycles: float  # avg cycles until system reflects update


def compute_contradiction_handling(result: BenchmarkResult) -> ContradictionResult:
    """Compute contradiction handling from benchmark results."""
    if not result.final_metrics or not result.final_metrics.contradiction_results:
        return ContradictionResult(0, 0, 0, 0)

    results = result.final_metrics.contradiction_results
    n = len(results)

    update_acc = sum(1 for r in results if r["update_accuracy"] > 0) / n
    stale_rate = sum(1 for r in results if r["stale_found"]) / n
    dual_rate = sum(1 for r in results if r["dual_return"]) / n

    # Correction latency: computed from metrics_over_time if available
    # For now, use a simplified approach based on category scores over time
    latency = _estimate_correction_latency(result)

    return ContradictionResult(
        update_accuracy=update_acc,
        stale_rate=stale_rate,
        dual_return_rate=dual_rate,
        correction_latency_cycles=latency,
    )


def _estimate_correction_latency(result: BenchmarkResult) -> float:
    """Estimate avg cycles until contradictions are correctly resolved.

    Looks at fact_update category scores at successive measurement points.
    The latency is roughly when the score goes from 0 to 1 after a contradiction.
    """
    fact_scores = []
    for cycle, metrics in result.metrics_over_time:
        cat = metrics.recall_by_category.get("fact_update", {})
        f1 = cat.get("f1", 0.0)
        fact_scores.append((cycle, f1))

    if len(fact_scores) < 2:
        return 0.0

    # Find first point where fact_update score exceeds 0.5
    # (rough proxy for "system has caught up to contradictions")
    for cycle, f1 in fact_scores:
        if f1 > 0.5:
            return float(cycle)

    return float(fact_scores[-1][0])  # never resolved
