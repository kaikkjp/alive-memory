"""Metric: Selective Forgetting — ability to remove specific memories on request."""

from __future__ import annotations

from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class SelectiveForgettingResult:
    """Selective forgetting metrics."""

    forget_success_rate: float  # fraction of forget directives that worked
    residual_recall_rate: float  # fraction where forgotten content still appears
    supported: bool  # False if adapter doesn't support forget


def compute_selective_forgetting(result: BenchmarkResult) -> SelectiveForgettingResult:
    """Compute selective forgetting metrics from benchmark result.

    Reads forget_verification scores from recall_by_category.
    """
    if not result.final_metrics:
        return SelectiveForgettingResult(
            forget_success_rate=0.0, residual_recall_rate=0.0, supported=False,
        )

    # Look for forget_verification category in recall_by_category
    by_cat = result.final_metrics.recall_by_category
    forget_data = by_cat.get("forget_verification", {})

    if not forget_data or forget_data.get("count", 0) == 0:
        return SelectiveForgettingResult(
            forget_success_rate=0.0, residual_recall_rate=0.0, supported=False,
        )

    # For forget verification, low recall = good (content was forgotten)
    # precision measures how clean results are after forgetting
    precision = forget_data.get("precision", 0.0)
    recall = forget_data.get("recall", 0.0)

    # Success = content NOT recalled (1 - recall of forgotten content)
    forget_success = 1.0 - recall
    residual_rate = recall

    return SelectiveForgettingResult(
        forget_success_rate=forget_success,
        residual_recall_rate=residual_rate,
        supported=True,
    )
