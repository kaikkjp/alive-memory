"""Drift detection — detect when behavioral traits are changing.

Extracted from engine/identity/drift.py.
Stripped: pipeline-specific event emission, parameter modification queries.
Kept: drift detection math, significance testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from alive_memory.config import AliveConfig
from alive_memory.storage.base import BaseStorage
from alive_memory.types import SelfModel


@dataclass
class DriftReport:
    """Report of detected behavioral drift."""
    trait: str
    direction: str  # "increase" or "decrease"
    magnitude: float  # absolute change
    old_value: float
    new_value: float
    confidence: float  # 0-1, how confident the drift is real
    window_cycles: int  # how many cycles the window covers
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


async def detect_drift(
    storage: BaseStorage,
    *,
    config: AliveConfig | None = None,
) -> list[DriftReport]:
    """Detect behavioral drift by comparing current traits to recent history.

    Looks at drift_history in the self-model and flags traits that have
    moved significantly in a consistent direction.

    Returns:
        List of DriftReports for traits with significant drift.
    """
    cfg = config or AliveConfig()
    threshold = cfg.get("identity.drift_threshold", 0.15)
    window = cfg.get("identity.drift_window", 50)

    model = await storage.get_self_model()
    reports: list[DriftReport] = []

    if not model.drift_history:
        return reports

    # Group drift events by trait
    trait_deltas: dict[str, list[dict]] = {}
    for entry in model.drift_history[-window:]:
        trait = entry.get("trait", "")
        if trait:
            trait_deltas.setdefault(trait, []).append(entry)

    for trait, deltas in trait_deltas.items():
        if len(deltas) < 2:
            continue

        # Compute net drift
        total_delta = sum(d.get("delta", 0) for d in deltas)
        magnitude = abs(total_delta)

        if magnitude >= threshold:
            # Compute consistency (are all deltas in the same direction?)
            same_direction = sum(
                1 for d in deltas
                if (d.get("delta", 0) > 0) == (total_delta > 0)
            )
            consistency = same_direction / len(deltas)
            confidence = min(1.0, consistency * (magnitude / threshold))

            current = model.traits.get(trait, 0.5)
            old_value = current - total_delta

            reports.append(DriftReport(
                trait=trait,
                direction="increase" if total_delta > 0 else "decrease",
                magnitude=magnitude,
                old_value=old_value,
                new_value=current,
                confidence=confidence,
                window_cycles=len(deltas),
            ))

    return reports
