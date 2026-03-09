"""Evaluator — score simulation results with mechanical metrics."""

from __future__ import annotations

from alive_memory.autotune.types import MemoryScore, RecallResult, SimulationResult


def score_recall(result: RecallResult) -> tuple[float, float]:
    """Score a single recall result. Returns (precision, completeness)."""
    expected = result.expected
    if expected is None:
        return 1.0, 1.0

    text = result.recalled_text.lower()

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


def score_simulation(result: SimulationResult) -> MemoryScore:
    """Score a full simulation result."""
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

    return MemoryScore(
        recall_precision=recall_precision,
        recall_completeness=recall_completeness,
        intake_acceptance_rate=acceptance,
        dedup_accuracy=0.0,  # Scored separately per scenario category
        decay_accuracy=0.0,
        recall_latency_ms=median_latency,
    )


def score_dedup_scenario(result: SimulationResult) -> float:
    """Score dedup accuracy: fewer duplicate moments = better dedup."""
    total = result.moments_recorded + result.moments_rejected
    if total == 0:
        return 0.0
    # Good dedup = high rejection rate for duplicate content
    return result.moments_rejected / total


def aggregate_scores(
    scores: dict[str, MemoryScore],
) -> float:
    """Aggregate per-scenario scores into a single composite. Lower = better."""
    if not scores:
        return 1.0

    composites = [s.composite for s in scores.values()]
    return sum(composites) / len(composites)
