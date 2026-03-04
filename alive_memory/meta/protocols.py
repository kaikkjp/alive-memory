"""Protocols for meta-controller extensibility.

Applications implement these protocols to supply domain-specific
metrics, drives, and stability checks to the meta-cognition system.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MetricsProvider(Protocol):
    """Application-supplied metric collection."""

    async def collect_metrics(self) -> dict[str, float]:
        """Collect current metric values. Keys are metric names, values are floats."""
        ...

    async def get_cycle_count(self) -> int:
        """Return the total number of cycles elapsed."""
        ...


@runtime_checkable
class DriveProvider(Protocol):
    """Application-supplied drive values and category mapping."""

    async def get_drive_values(self) -> dict[str, float]:
        """Return current drive values by name."""
        ...

    def get_category_drive_map(self) -> dict[str, list[str]]:
        """Map parameter categories to the drive names they govern.

        Example: {"consolidation": ["curiosity"], "social": ["social", "expression"]}
        """
        ...
