"""Metric 7: Noise Resilience — can the system distinguish signal from noise?"""

from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class NoiseResilienceResult:
    signal_recall: float  # can it find important memories in noisy data?
    noise_intrusion: float  # how much noise in recall results?
    needle_recall_rate: float  # can it find rare important events?


def compute_noise_resilience(result: BenchmarkResult) -> NoiseResilienceResult:
    """Compute noise resilience from benchmark results.

    Best measured on the stress_test stream which has 50% noise and
    planted needles. Falls back to overall noise_ratio for other streams.
    """
    if not result.final_metrics:
        return NoiseResilienceResult(0, 0, 0)

    summary = result.final_metrics.recall_summary
    by_cat = result.final_metrics.recall_by_category

    # Signal recall: overall recall on non-noise queries
    signal_recall = summary.get("recall", 0.0)

    # Noise intrusion: ratio of irrelevant results
    noise_intrusion = summary.get("noise_ratio", 0.0)

    # Needle recall: from needle_in_haystack category
    needle = by_cat.get("needle_in_haystack", {})
    needle_recall = needle.get("recall", 0.0)

    return NoiseResilienceResult(
        signal_recall=signal_recall,
        noise_intrusion=noise_intrusion,
        needle_recall_rate=needle_recall,
    )
