"""Closed-loop evaluation of parameter adjustments.

After the meta-controller makes an adjustment, this module
evaluates whether the change improved the target metric,
and reverts if it caused degradation or side effects.
"""

from __future__ import annotations

from alive_memory.meta.controller import Experiment, classify_outcome
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
