"""Metric: Cold Contribution — cold vs hot memory tier analysis (alive-only)."""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.runner import BenchmarkResult


@dataclass
class ColdContributionResult:
    """Memory tier contribution metrics."""

    cold_pct: float  # percentage of results from cold tier
    hot_pct: float  # percentage of results from hot tier
    reflection_pct: float  # percentage from reflections
    tier_distribution: dict[str, float] = field(default_factory=dict)
    supported: bool = False


def compute_cold_contribution(result: BenchmarkResult) -> ColdContributionResult:
    """Aggregate tier distribution across all measurement points."""
    total_by_tier: dict[str, int] = {}

    for _cycle, metrics in result.metrics_over_time:
        for tier, count in metrics.tier_distribution.items():
            total_by_tier[tier] = total_by_tier.get(tier, 0) + count

    # Also include final metrics
    if result.final_metrics:
        for tier, count in result.final_metrics.tier_distribution.items():
            total_by_tier[tier] = total_by_tier.get(tier, 0) + count

    total = sum(total_by_tier.values())
    if total == 0 or (len(total_by_tier) == 1 and "unknown" in total_by_tier):
        return ColdContributionResult(
            cold_pct=0.0, hot_pct=0.0, reflection_pct=0.0, supported=False,
        )

    tier_pcts = {tier: count / total for tier, count in total_by_tier.items()}

    return ColdContributionResult(
        cold_pct=tier_pcts.get("cold", 0.0),
        hot_pct=tier_pcts.get("hot", 0.0),
        reflection_pct=tier_pcts.get("reflection", 0.0),
        tier_distribution=tier_pcts,
        supported=True,
    )
