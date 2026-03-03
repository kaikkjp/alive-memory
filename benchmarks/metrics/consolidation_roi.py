"""Metric: Consolidation ROI — cost-effectiveness of memory maintenance."""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.metrics.resource_efficiency import PRICING
from benchmarks.runner import BenchmarkResult


@dataclass
class ConsolidationROIResult:
    """Cost-effectiveness of consolidation."""

    f1_per_dollar: float
    f1_improvement: float  # final F1 - first F1
    estimated_cost: float
    marginal_curve: list[tuple[int, float]] = field(default_factory=list)  # (cycle, F1)
    classification: str = "unknown"  # efficient | moderate | wasteful


def compute_consolidation_roi(
    result: BenchmarkResult,
    model: str = "default",
) -> ConsolidationROIResult:
    """Compute consolidation ROI from benchmark result.

    Pure post-hoc from metrics_over_time (F1 values) and final_stats (total_tokens).
    """
    # Extract F1 over time
    f1_curve = []
    for cycle, metrics in result.metrics_over_time:
        f1 = metrics.recall_summary.get("f1", 0.0)
        f1_curve.append((cycle, f1))

    if not f1_curve:
        return ConsolidationROIResult(
            f1_per_dollar=0.0, f1_improvement=0.0,
            estimated_cost=0.0, classification="unknown",
        )

    first_f1 = f1_curve[0][1]
    final_f1 = f1_curve[-1][1]
    f1_improvement = final_f1 - first_f1

    # Cost estimate from tokens
    total_tokens = 0
    if result.final_stats:
        total_tokens = result.final_stats.total_tokens

    pricing = PRICING.get(model, PRICING["default"])
    estimated_cost = total_tokens / 1_000_000 * (pricing["input"] + pricing["output"]) / 2

    # F1 per dollar
    f1_per_dollar = f1_improvement / max(estimated_cost, 0.001)

    # Classification
    if f1_per_dollar > 10:
        classification = "efficient"
    elif f1_per_dollar >= 1:
        classification = "moderate"
    else:
        classification = "wasteful"

    return ConsolidationROIResult(
        f1_per_dollar=f1_per_dollar,
        f1_improvement=f1_improvement,
        estimated_cost=estimated_cost,
        marginal_curve=f1_curve,
        classification=classification,
    )
