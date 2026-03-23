"""Closed-loop evaluation of parameter adjustments.

Part of alive_cognition (moved from alive_memory.meta.evaluation).
After the meta-controller makes an adjustment, this module
evaluates whether the change improved the target metric,
and reverts if it caused degradation or side effects.
"""

from __future__ import annotations

from datetime import UTC, datetime

from alive_cognition.meta.controller import Experiment, MetricTarget, classify_outcome
from alive_cognition.meta.protocols import MetricsProvider
from alive_memory.storage.base import BaseStorage


async def evaluate_experiment(
    experiment: Experiment,
    current_metrics: dict[str, float],
    target_min: float,
    target_max: float,
    storage: BaseStorage,
) -> Experiment:
    """Evaluate a pending experiment against current metrics.

    Args:
        experiment: The experiment to evaluate.
        current_metrics: Current metric values.
        target_min: Target range minimum.
        target_max: Target range maximum.
        storage: Storage backend (for reverting if needed).

    Returns:
        Updated experiment with outcome.
    """
    current_value = current_metrics.get(experiment.target_metric)
    if current_value is None:
        experiment.outcome = "neutral"
        return experiment

    outcome = classify_outcome(
        experiment.metric_at_change,
        current_value,
        target_min,
        target_max,
    )
    experiment.outcome = outcome

    # Revert if degraded
    if outcome == "degraded":
        await storage.set_parameter(
            experiment.param_key,
            experiment.old_value,
            reason=f"meta-revert: {experiment.target_metric} degraded",
        )
        experiment.confidence = max(0.1, experiment.confidence - 0.2)

    elif outcome == "improved":
        experiment.confidence = min(1.0, experiment.confidence + 0.1)

    return experiment


async def evaluate_pending_experiments(
    storage: BaseStorage,
    current_metrics: dict[str, float],
    targets: list[MetricTarget],
    *,
    min_age_cycles: int = 2,
    metrics_provider: MetricsProvider | None = None,
) -> list[Experiment]:
    """Evaluate all pending experiments that are old enough.

    Age-gating: experiments must be at least min_age_cycles old
    to allow effects to manifest before judging.

    Args:
        storage: Storage backend.
        current_metrics: Current metric values.
        targets: Metric targets for finding target ranges.
        min_age_cycles: Minimum cycles before evaluating.
        metrics_provider: Optional provider (unused here, reserved for future).

    Returns:
        List of evaluated experiments.
    """
    pending = await storage.get_pending_experiments(min_age_cycles=min_age_cycles)

    # Build target range lookup
    target_ranges: dict[str, tuple[float, float]] = {}
    for t in targets:
        target_ranges[t.name] = (t.min_value, t.max_value)

    evaluated: list[Experiment] = []
    now = datetime.now(UTC)

    for row in pending:
        metric_name = row["target_metric"]
        if metric_name not in target_ranges:
            continue

        target_min, target_max = target_ranges[metric_name]

        exp = Experiment(
            id=row["id"],
            param_key=row["param_key"],
            old_value=row["old_value"],
            new_value=row["new_value"],
            target_metric=row["target_metric"],
            metric_at_change=row["metric_at_change"],
            confidence=row["confidence"],
            side_effects=row["side_effects"],
            cycle_at_creation=row.get("cycle_at_creation", 0),
        )

        exp = await evaluate_experiment(exp, current_metrics, target_min, target_max, storage)

        # Persist confidence to storage
        await storage.set_confidence(exp.param_key, exp.target_metric, exp.confidence)

        # Persist experiment outcome
        await storage.update_experiment(
            exp.id,
            {
                "outcome": exp.outcome,
                "confidence": exp.confidence,
                "side_effects": exp.side_effects,
                "evaluated_at": now.isoformat(),
            },
        )

        evaluated.append(exp)

    return evaluated


def detect_side_effects(
    experiment: Experiment,
    metrics_before: dict[str, float],
    metrics_after: dict[str, float],
    targets: dict[str, tuple[float, float]],
) -> list[str]:
    """Check if an adjustment caused side effects on other metrics.

    A side effect = a metric was in-range before, out-of-range now.

    Returns list of affected metric names.
    """
    side_effects: list[str] = []

    for name, (lo, hi) in targets.items():
        if name == experiment.target_metric:
            continue

        before = metrics_before.get(name)
        after = metrics_after.get(name)
        if before is None or after is None:
            continue

        was_in_range = lo <= before <= hi
        now_out_of_range = after < lo or after > hi

        if was_in_range and now_out_of_range:
            side_effects.append(name)

    return side_effects
