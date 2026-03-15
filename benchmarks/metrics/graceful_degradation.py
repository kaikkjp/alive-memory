"""Metric: Graceful Degradation — performance under pressure."""

from __future__ import annotations

import math
from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class GracefulDegradationResult:
    """Performance-under-pressure metrics."""

    quality_retention: float  # final F1 / first F1
    p999_ingest_ms: float
    p999_recall_ms: float
    p999_consolidate_ms: float
    latency_growth_rate: float  # slope of p95 latency vs log(cycle)
    quality_latency_tradeoff: float  # F1 retention / latency growth


def _p999(values: list[float]) -> float:
    """Compute p99.9 from a list of values (in seconds), return in ms."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = min(int(len(sorted_v) * 0.999), len(sorted_v) - 1)
    return sorted_v[idx] * 1000


def _linear_regression_slope(x: list[float], y: list[float]) -> float:
    """Simple linear regression, return slope."""
    n = len(x)
    if n < 2:
        return 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y, strict=False))
    denominator = sum((xi - mean_x) ** 2 for xi in x)

    if denominator == 0:
        return 0.0
    return numerator / denominator


def compute_graceful_degradation(result: BenchmarkResult) -> GracefulDegradationResult:
    """Compute graceful degradation from benchmark result."""
    # Quality retention
    f1_values = []
    for _cycle, metrics in result.metrics_over_time:
        f1 = metrics.recall_summary.get("f1", 0.0)
        f1_values.append(f1)

    if result.final_metrics:
        final_f1 = result.final_metrics.recall_summary.get("f1", 0.0)
        f1_values.append(final_f1)

    quality_retention = 0.0
    if len(f1_values) >= 2 and f1_values[0] > 0:
        quality_retention = f1_values[-1] / f1_values[0]

    # p999 latencies
    lat = result.latencies
    p999_ingest = _p999(lat.get("ingest", []))
    p999_recall = _p999(lat.get("recall", []))
    p999_consolidate = _p999(lat.get("consolidate", []))

    # Latency growth rate: linear regression of p95 recall latency at each
    # measurement point vs log(cycle)
    # We approximate by splitting recall latencies into buckets per measurement point
    log_cycles = []
    p95_latencies = []

    # Use metrics_over_time cycle numbers to approximate latency at each point
    all_recall = lat.get("recall", [])
    if all_recall and result.metrics_over_time:
        n_points = len(result.metrics_over_time)
        chunk_size = max(1, len(all_recall) // max(n_points, 1))

        for i, (cycle, _) in enumerate(result.metrics_over_time):
            start = i * chunk_size
            end = min(start + chunk_size, len(all_recall))
            chunk = all_recall[start:end]
            if chunk and cycle > 0:
                sorted_chunk = sorted(chunk)
                p95_idx = min(int(len(sorted_chunk) * 0.95), len(sorted_chunk) - 1)
                p95_ms = sorted_chunk[p95_idx] * 1000
                log_cycles.append(math.log(cycle))
                p95_latencies.append(p95_ms)

    latency_growth = _linear_regression_slope(log_cycles, p95_latencies)

    # Quality-latency tradeoff
    tradeoff = 0.0
    if latency_growth > 0:
        tradeoff = quality_retention / latency_growth
    elif quality_retention > 0:
        tradeoff = float("inf")

    return GracefulDegradationResult(
        quality_retention=quality_retention,
        p999_ingest_ms=p999_ingest,
        p999_recall_ms=p999_recall,
        p999_consolidate_ms=p999_consolidate,
        latency_growth_rate=latency_growth,
        quality_latency_tradeoff=tradeoff,
    )
