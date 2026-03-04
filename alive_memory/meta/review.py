"""Meta-review: trait stability and self-modification review.

Runs during sleep to check whether recent parameter changes
have degraded governed drives, and reverts if so.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from alive_memory.config import AliveConfig
from alive_memory.meta.protocols import DriveProvider
from alive_memory.storage.base import BaseStorage

logger = logging.getLogger(__name__)


@dataclass
class StabilityReport:
    """Result of trait stability review."""
    trait: str
    stability_score: float  # 0-1, based on consistency over recent cycles
    direction: str  # "stable", "increasing", "decreasing", "oscillating"


@dataclass
class ReviewResult:
    """Outcome of a full meta-review cycle."""
    stability_reports: list[StabilityReport] = field(default_factory=list)
    reverted_params: list[str] = field(default_factory=list)


async def run_meta_review(
    storage: BaseStorage,
    *,
    drive_provider: DriveProvider | None = None,
    config: AliveConfig | None = None,
    consistency_window: int = 3,
) -> ReviewResult:
    """Run meta-review: check trait stability and revert harmful self-mods.

    Args:
        storage: Storage backend.
        drive_provider: Optional provider for drive values and category mapping.
        config: Configuration.
        consistency_window: Number of recent cycles to check for stability.

    Returns:
        ReviewResult with stability reports and any reverted parameters.
    """
    stability = await review_trait_stability(storage, window=consistency_window)
    reverted: list[str] = []

    if drive_provider is not None:
        reverted = await review_self_modifications(storage, drive_provider)

    return ReviewResult(stability_reports=stability, reverted_params=reverted)


async def review_trait_stability(
    storage: BaseStorage,
    *,
    window: int = 3,
) -> list[StabilityReport]:
    """Check trait consistency over recent drift history.

    Looks at the last ``window`` drift entries per trait.
    If all deltas have the same sign -> directional.
    If mixed signs -> oscillating.
    If magnitude < threshold -> stable.
    Stability score = 1.0 - normalized_variance.
    """
    model = await storage.get_self_model()
    history = model.drift_history

    # Group drift_history by trait, take last `window` entries
    by_trait: dict[str, list[float]] = defaultdict(list)
    for entry in history:
        trait = entry.get("trait", "")
        delta = entry.get("delta", 0.0)
        if trait:
            by_trait[trait].append(delta)

    reports: list[StabilityReport] = []
    for trait, deltas in by_trait.items():
        recent = deltas[-window:]
        if not recent:
            continue

        # Compute direction
        positive = sum(1 for d in recent if d > 0)
        negative = sum(1 for d in recent if d < 0)

        abs_deltas = [abs(d) for d in recent]
        mean_magnitude = sum(abs_deltas) / len(abs_deltas)

        if mean_magnitude < 0.02:
            direction = "stable"
        elif positive > 0 and negative > 0:
            direction = "oscillating"
        elif positive > 0:
            direction = "increasing"
        else:
            direction = "decreasing"

        # Stability score: 1.0 - normalized variance of deltas
        mean_delta = sum(recent) / len(recent)
        variance = sum((d - mean_delta) ** 2 for d in recent) / len(recent)
        # Normalize: max expected variance ~ 0.25 (deltas ranging -0.5 to 0.5)
        normalized_var = min(1.0, variance / 0.25)
        stability_score = max(0.0, 1.0 - normalized_var)

        reports.append(StabilityReport(
            trait=trait,
            stability_score=stability_score,
            direction=direction,
        ))

    return reports


async def review_self_modifications(
    storage: BaseStorage,
    drive_provider: DriveProvider,
    *,
    degradation_threshold: float = 0.15,
) -> list[str]:
    """Review recent parameter changes and revert if governed drives degraded.

    For each parameter category, check if the drives it governs have degraded
    since the parameter was last modified. If so, revert the parameter to its
    previous value (default_value).

    Returns list of reverted parameter keys.
    """
    category_map = drive_provider.get_category_drive_map()
    drive_values = await drive_provider.get_drive_values()
    params = await storage.get_parameters()

    reverted: list[str] = []
    # Equilibrium assumed at 0.5 for drives
    equilibrium = 0.5

    for category, governed_drives in category_map.items():
        # Check if any governed drives have degraded
        degraded = False
        for drive_name in governed_drives:
            drive_val = drive_values.get(drive_name)
            if drive_val is not None and drive_val < (equilibrium - degradation_threshold):
                degraded = True
                break

        if not degraded:
            continue

        # Find params with this category and revert them
        for param_key in list(params.keys()):
            if not param_key.startswith(category):
                continue

            # Revert to default by getting bounds (default_value is stored separately)
            # Use set_parameter with reason to log the revert
            # For simplicity, revert to 0.5 (neutral) as default
            # In practice, the application would store default_value in the parameters table
            min_b, max_b = await storage.get_parameter_bounds(param_key)
            default_value = 0.5
            if min_b is not None:
                default_value = max(min_b, default_value)
            if max_b is not None:
                default_value = min(max_b, default_value)

            current = params[param_key]
            if abs(current - default_value) < 0.001:
                continue

            await storage.set_parameter(
                param_key,
                default_value,
                reason=f"meta-review: {category} drives degraded, reverting {param_key}",
            )
            reverted.append(param_key)
            logger.info("Reverted %s to %.3f (governed drives degraded)", param_key, default_value)

    return reverted
