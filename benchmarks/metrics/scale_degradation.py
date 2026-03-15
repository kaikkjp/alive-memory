"""Metric 4: Scale Degradation — does recall quality drop as memory grows?"""

import math
from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class ScaleDegradationResult:
    quality_at_100: float
    quality_at_1000: float
    quality_at_5000: float
    quality_at_10000: float
    quality_at_50000: float  # stress test only, 0 if not measured
    degradation_rate: float  # slope of quality over log(events)
    storage_growth_rate: float  # bytes per event over time


def compute_scale_degradation(result: BenchmarkResult) -> ScaleDegradationResult:
    """Compute scale degradation from metrics over time."""
    point_map: dict[int, float] = {}
    storage_points: list[tuple[int, int]] = []

    for cycle, metrics in result.metrics_over_time:
        f1 = metrics.recall_summary.get("f1", 0.0)
        point_map[cycle] = f1
        if metrics.stats:
            storage_points.append((cycle, metrics.stats.storage_bytes))

    # Degradation rate: linear regression of F1 on log(cycle)
    deg_rate = _compute_degradation_rate(
        [(c, f) for c, f in point_map.items() if c > 0]
    )

    # Storage growth rate: bytes per event
    storage_rate = 0.0
    if len(storage_points) >= 2:
        first_cycle, first_bytes = storage_points[0]
        last_cycle, last_bytes = storage_points[-1]
        event_delta = last_cycle - first_cycle
        if event_delta > 0:
            storage_rate = (last_bytes - first_bytes) / event_delta

    return ScaleDegradationResult(
        quality_at_100=point_map.get(100, 0.0),
        quality_at_1000=point_map.get(1000, 0.0),
        quality_at_5000=point_map.get(5000, 0.0),
        quality_at_10000=point_map.get(10000, 0.0),
        quality_at_50000=point_map.get(50000, 0.0),
        degradation_rate=deg_rate,
        storage_growth_rate=storage_rate,
    )


def _compute_degradation_rate(points: list[tuple[int, float]]) -> float:
    """Linear regression slope of F1 on log(cycle).

    Negative = degradation. Zero = stable. Positive = improvement.
    """
    if len(points) < 2:
        return 0.0

    xs = [math.log(c) for c, _ in points]
    ys = [f for _, f in points]

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False))
    den = sum((x - mean_x) ** 2 for x in xs)

    if abs(den) < 1e-10:
        return 0.0

    return num / den
