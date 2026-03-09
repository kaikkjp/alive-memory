"""Evaluator — score simulation results with mechanical metrics."""

from __future__ import annotations

from alive_memory.autotune.types import MemoryScore, RecallResult, SimulationResult


def score_recall(result: RecallResult) -> tuple[float, float]:
    """Score a single recall result. Returns (precision, completeness)."""
    expected = result.expected
    if expected is None:
        return 1.0, 1.0

    text = result.recalled_text.lower()

    # Check min_results requirement
    if result.num_results < expected.min_results:
        return 0.0, 0.0

    # Completeness: % of must_contain keywords found
    if expected.must_contain:
        found = sum(1 for kw in expected.must_contain if kw.lower() in text)
        completeness = found / len(expected.must_contain)
    else:
        completeness = 1.0

    # Precision: no must_not_contain violations
    if expected.must_not_contain:
        violations = sum(1 for kw in expected.must_not_contain if kw.lower() in text)
        precision = 1.0 - (violations / len(expected.must_not_contain))
    else:
        precision = 1.0

    return precision, completeness


def score_simulation(result: SimulationResult, *, category: str = "") -> MemoryScore:
    """Score a full simulation result.

    Args:
        result: The simulation result to score.
        category: Scenario category for category-specific scoring.
    """
    # Recall metrics
    precisions = []
    completions = []
    latencies = []

    for rr in result.recall_results:
        p, c = score_recall(rr)
        precisions.append(p)
        completions.append(c)
        latencies.append(rr.elapsed_ms)

    recall_precision = sum(precisions) / len(precisions) if precisions else 0.0
    recall_completeness = sum(completions) / len(completions) if completions else 0.0

    # Intake acceptance rate
    total_intake = result.moments_recorded + result.moments_rejected
    acceptance = result.moments_recorded / total_intake if total_intake > 0 else 0.0

    # Median recall latency
    if latencies:
        sorted_lat = sorted(latencies)
        mid = len(sorted_lat) // 2
        median_latency = float(sorted_lat[mid])
    else:
        median_latency = 0.0

    # Category-specific scoring
    dedup_accuracy = 0.0
    decay_accuracy = 0.0

    if category == "dedup":
        # Good dedup = recall still finds the key facts (not over-filtered)
        # AND some duplicates were rejected. Use recall completeness as primary
        # signal and add a small bonus for rejecting some duplicates.
        rejection_rate = result.moments_rejected / total_intake if total_intake > 0 else 0.0
        # Penalize both extremes: 0 rejections (no dedup) and near-total rejection (over-filtering)
        dedup_accuracy = recall_completeness * min(rejection_rate * 2.0, 1.0)

    if category == "forgetting":
        # Forgetting quality is measured by recall — important info found, chitchat not.
        # Use recall completeness as a proxy for decay accuracy.
        decay_accuracy = recall_completeness

    return MemoryScore(
        recall_precision=recall_precision,
        recall_completeness=recall_completeness,
        intake_acceptance_rate=acceptance,
        dedup_accuracy=dedup_accuracy,
        decay_accuracy=decay_accuracy,
        recall_latency_ms=median_latency,
    )


def _weighted_composite(score: MemoryScore, weights: dict | None) -> float:
    """Compute composite with custom weights. Lower = better."""
    if weights is None:
        return score.composite

    w = {
        "recall_completeness": weights.get("recall_completeness", 0.35),
        "recall_precision": weights.get("recall_precision", 0.30),
        "dedup_accuracy": weights.get("dedup_accuracy", 0.15),
        "decay_accuracy": weights.get("decay_accuracy", 0.10),
        "intake_acceptance_rate": weights.get("intake_acceptance_rate", 0.10),
    }
    quality = (
        w["recall_completeness"] * score.recall_completeness
        + w["recall_precision"] * score.recall_precision
        + w["dedup_accuracy"] * score.dedup_accuracy
        + w["decay_accuracy"] * score.decay_accuracy
        + w["intake_acceptance_rate"] * score.intake_acceptance_rate
    )
    latency_penalty = min(score.recall_latency_ms / 1000.0, 1.0) * 0.05
    return 1.0 - quality + latency_penalty


def aggregate_scores(
    scores: dict[str, MemoryScore],
    *,
    scoring_weights: dict | None = None,
) -> float:
    """Aggregate per-scenario scores into a single composite. Lower = better."""
    if not scores:
        return 1.0

    composites = [_weighted_composite(s, scoring_weights) for s in scores.values()]
    return sum(composites) / len(composites)
