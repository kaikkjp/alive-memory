"""Meta-controller — self-tuning parameter adjustments.

Extracted from engine/sleep/meta_controller.py.
Stripped: application-specific metric names, DB-specific queries.
Kept: metric-driven adjustment logic, confidence tracking, revert logic,
      adaptive cooldown, outcome classification.

Three-tier hierarchy (Tier 2):
  Tier 1: Operator hard floor (config) — immutable
  Tier 2: Meta-controller homeostasis (this) — sleep-phase adjustments
  Tier 3: Conscious modify_self — deliberate, reflection-required
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from alive_memory.config import AliveConfig
from alive_memory.meta.protocols import MetricsProvider
from alive_memory.storage.base import BaseStorage


@dataclass
class MetricTarget:
    """A metric with a target range for the meta-controller."""
    name: str
    min_value: float
    max_value: float
    param_key: str  # parameter to adjust
    adjustment_step: float = 0.05
    current_value: float | None = None


@dataclass
class Experiment:
    """A recorded parameter adjustment experiment."""
    id: str
    param_key: str
    old_value: float
    new_value: float
    target_metric: str
    metric_at_change: float
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    outcome: str = "pending"  # pending, improved, degraded, neutral
    confidence: float = 0.5
    side_effects: list[str] = field(default_factory=list)
    cycle_at_creation: int = 0


@dataclass
class HardFloor:
    """Tier 1 absolute bounds. Applied last, cannot be overridden by meta-controller."""
    param_key: str
    min_bound: float | None = None
    max_bound: float | None = None


async def _apply_hard_floors(
    storage: BaseStorage,
    param_key: str,
    value: float,
) -> float:
    """Clamp value to Tier 1 hard floor bounds from storage."""
    min_b, max_b = await storage.get_parameter_bounds(param_key)
    if min_b is not None:
        value = max(min_b, value)
    if max_b is not None:
        value = min(max_b, value)
    return value


async def run_meta_controller(
    storage: BaseStorage,
    metrics: dict[str, float] | None = None,
    targets: list[MetricTarget] | None = None,
    *,
    config: AliveConfig | None = None,
    metrics_provider: MetricsProvider | None = None,
) -> list[Experiment]:
    """Run the meta-controller: detect out-of-range metrics and adjust parameters.

    Args:
        storage: Storage backend.
        metrics: Current metric name → value mapping. Takes precedence over provider.
        targets: List of metric targets with adjustment rules.
        config: Configuration parameters.
        metrics_provider: Optional provider for metric collection.

    Returns:
        List of experiments (adjustments made).
    """
    if targets is None:
        targets = []

    # Resolve metrics: explicit dict takes precedence over provider
    if metrics is None and metrics_provider is not None:
        metrics = await metrics_provider.collect_metrics()
    if metrics is None:
        return []

    cycle_count = 0
    if metrics_provider is not None:
        cycle_count = await metrics_provider.get_cycle_count()
    else:
        cycle_count = await storage.get_cycle_count()

    experiments: list[Experiment] = []
    params = await storage.get_parameters()

    for target in targets:
        value = metrics.get(target.name)
        if value is None:
            continue

        target.current_value = value

        # Check if metric is in range
        if target.min_value <= value <= target.max_value:
            continue  # healthy, no adjustment needed

        # Out of range — determine adjustment direction
        current_param = params.get(target.param_key)
        if current_param is None:
            continue

        if value < target.min_value:
            # Metric too low → increase parameter
            new_value = current_param + target.adjustment_step
        else:
            # Metric too high → decrease parameter
            new_value = current_param - target.adjustment_step

        # Apply soft bounded adjustment
        new_value = max(0.0, min(1.0, new_value))

        # Apply Tier 1 hard floor bounds
        new_value = await _apply_hard_floors(storage, target.param_key, new_value)

        if abs(new_value - current_param) < 0.001:
            continue  # No meaningful change

        await storage.set_parameter(
            target.param_key,
            new_value,
            reason=f"meta: {target.name}={value:.3f} out of [{target.min_value}, {target.max_value}]",
        )

        # Load persisted confidence for this param→metric link
        confidence = await storage.get_confidence(target.param_key, target.name)

        exp = Experiment(
            id=str(uuid.uuid4()),
            param_key=target.param_key,
            old_value=current_param,
            new_value=new_value,
            target_metric=target.name,
            metric_at_change=value,
            confidence=confidence,
            cycle_at_creation=cycle_count,
        )

        # Persist experiment to storage
        await storage.save_experiment({
            "id": exp.id,
            "param_key": exp.param_key,
            "old_value": exp.old_value,
            "new_value": exp.new_value,
            "target_metric": exp.target_metric,
            "metric_at_change": exp.metric_at_change,
            "outcome": exp.outcome,
            "confidence": exp.confidence,
            "side_effects": exp.side_effects,
            "created_at": exp.created_at.isoformat(),
            "cycle_at_creation": exp.cycle_at_creation,
        })

        experiments.append(exp)

    return experiments


async def request_correction(
    storage: BaseStorage,
    param_key: str,
    target_value: float,
    reason: str = "identity-correction",
) -> None:
    """Emergency parameter reset requested by identity evolution.

    Bypasses normal experiment flow — applies immediately and logs.
    Still respects hard floor bounds.
    """
    target_value = await _apply_hard_floors(storage, param_key, target_value)
    await storage.set_parameter(param_key, target_value, reason=reason)


def classify_outcome(
    metric_at_change: float,
    metric_after: float,
    target_min: float,
    target_max: float,
) -> str:
    """Classify an experiment outcome.

    Returns: 'improved', 'degraded', or 'neutral'.
    """
    # Distance from target range
    def distance_from_range(v: float) -> float:
        if v < target_min:
            return target_min - v
        if v > target_max:
            return v - target_max
        return 0.0

    dist_before = distance_from_range(metric_at_change)
    dist_after = distance_from_range(metric_after)

    relative_change = (dist_before - dist_after) / max(dist_before, 0.01)

    if relative_change > 0.05:
        return "improved"
    elif relative_change < -0.05:
        return "degraded"
    return "neutral"


def compute_adaptive_cooldown(
    base_cooldown: int,
    confidence: float,
) -> int:
    """Scale cooldown by confidence level.

    High confidence → shorter cooldown (more willing to adjust).
    Low confidence → longer cooldown (more cautious).
    """
    if confidence > 0.8:
        factor = 0.7
    elif confidence > 0.5:
        factor = 1.0
    elif confidence > 0.3:
        factor = 1.5
    else:
        factor = 2.0

    return max(1, int(base_cooldown * factor))
