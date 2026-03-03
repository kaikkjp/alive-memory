"""Metric 1: Recall Accuracy — does the system retrieve the right memories?"""

from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class RecallAccuracyResult:
    """Aggregate recall accuracy across all measurement points."""

    precision: float
    recall: float
    f1: float
    mrr: float
    noise_ratio: float


def compute_recall_accuracy(result: BenchmarkResult) -> RecallAccuracyResult:
    """Extract final recall accuracy from a benchmark result."""
    if not result.final_metrics:
        return RecallAccuracyResult(0, 0, 0, 0, 0)

    s = result.final_metrics.recall_summary
    return RecallAccuracyResult(
        precision=s.get("precision", 0.0),
        recall=s.get("recall", 0.0),
        f1=s.get("f1", 0.0),
        mrr=s.get("mrr", 0.0),
        noise_ratio=s.get("noise_ratio", 0.0),
    )


def compute_recall_at_points(
    result: BenchmarkResult,
) -> list[tuple[int, float]]:
    """Extract recall F1 at each measurement point (for degradation curve)."""
    points = []
    for cycle, metrics in result.metrics_over_time:
        f1 = metrics.recall_summary.get("f1", 0.0)
        points.append((cycle, f1))
    return points
