"""Identity evolution — four-step resolution for behavioral changes.

Extracted from engine/identity/evolution.py.
Enhanced with IdentityEvolution class, GuardRailConfig, CorrectionProvider
protocol, and event hooks.

Four-step hierarchy:
  1. Guard rails — protected trait bounds → CORRECT
  2. Sustained drift — persistent high-confidence → ACCEPT
  3. Correction provider — external system → CORRECT or DEFER
  4. Baseline shift — moderate confidence → ACCEPT or DEFER
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from alive_memory.identity.drift import DriftReport, DriftResult
from alive_memory.storage.base import BaseStorage


# ── Types ─────────────────────────────────────────────────────────


class EvolutionAction(Enum):
    ACCEPT = "accept"
    CORRECT = "correct"
    DEFER = "defer"


@dataclass
class EvolutionDecision:
    """Result of evaluating a drift report."""

    action: str  # "accept", "correct", "defer" (kept as str for compat)
    trait: str
    reason: str
    correction_value: float | None = None
    sustained_cycles: int = 0


@dataclass
class GuardRailConfig:
    """Configuration for identity protection."""

    protected_traits: dict[str, tuple[float, float]] = field(
        default_factory=dict
    )
    max_updates_per_sleep: int = 5
    min_sustained_cycles: int = 3


class CorrectionProvider(Protocol):
    """Protocol for external correction mechanisms (e.g., meta-controller)."""

    async def request_correction(
        self, trait: str, target: float, reason: str
    ) -> bool: ...


# ── IdentityEvolution class ──────────────────────────────────────


class IdentityEvolution:
    """Manages identity evolution decisions with guard rails and event hooks."""

    def __init__(
        self,
        storage: BaseStorage,
        guard_rails: GuardRailConfig | None = None,
        correction_provider: CorrectionProvider | None = None,
        on_decision: Callable[[EvolutionDecision], Awaitable[None]]
        | None = None,
    ):
        self._storage = storage
        self._guard_rails = guard_rails or GuardRailConfig()
        self._correction_provider = correction_provider
        self._on_decision = on_decision
        self._updates_this_sleep: int = 0

    async def evaluate(
        self, report: DriftReport | DriftResult
    ) -> EvolutionDecision:
        """Four-step decision sequence."""
        if isinstance(report, DriftResult):
            return await self._evaluate_drift_result(report)
        return await self._evaluate_drift_report(report)

    async def _evaluate_drift_report(
        self, report: DriftReport
    ) -> EvolutionDecision:
        """Evaluate a per-trait DriftReport through the four-step sequence."""
        gr = self._guard_rails

        # Step 1: Guard rails
        if report.trait in gr.protected_traits:
            lo, hi = gr.protected_traits[report.trait]
            if report.new_value < lo:
                return EvolutionDecision(
                    action="correct",
                    trait=report.trait,
                    reason=f"Trait '{report.trait}' drifted below protected minimum ({lo})",
                    correction_value=lo,
                )
            if report.new_value > hi:
                return EvolutionDecision(
                    action="correct",
                    trait=report.trait,
                    reason=f"Trait '{report.trait}' drifted above protected maximum ({hi})",
                    correction_value=hi,
                )

        # Step 2: Sustained drift
        if (
            report.window_cycles >= gr.min_sustained_cycles
            and report.confidence > 0.7
            and report.magnitude > 0.1
        ):
            return EvolutionDecision(
                action="accept",
                trait=report.trait,
                reason=f"Consistent {report.direction} drift (confidence: {report.confidence:.2f})",
                sustained_cycles=report.window_cycles,
            )

        # Step 3: Correction provider
        if self._correction_provider and 0.4 < report.confidence < 0.7:
            accepted = await self._correction_provider.request_correction(
                report.trait,
                report.new_value,
                f"Moderate drift: {report.direction} {report.magnitude:.2f}",
            )
            if accepted:
                return EvolutionDecision(
                    action="correct",
                    trait=report.trait,
                    reason="Correction provider accepted correction",
                    correction_value=report.old_value,
                )
            return EvolutionDecision(
                action="defer",
                trait=report.trait,
                reason="Correction provider deferred",
            )

        # Step 4: Baseline shift
        if self._updates_this_sleep >= gr.max_updates_per_sleep:
            return EvolutionDecision(
                action="defer",
                trait=report.trait,
                reason="Update limit reached for this sleep cycle",
            )

        if report.confidence >= 0.4 and report.magnitude > 0.2:
            return EvolutionDecision(
                action="accept",
                trait=report.trait,
                reason=f"Moderate {report.direction} drift, magnitude significant ({report.magnitude:.2f})",
            )

        return EvolutionDecision(
            action="defer",
            trait=report.trait,
            reason="Ambiguous drift, needs operator review",
        )

    async def _evaluate_drift_result(
        self, result: DriftResult
    ) -> EvolutionDecision:
        """Evaluate a composite DriftResult."""
        if result.severity == "none":
            return EvolutionDecision(
                action="defer",
                trait="composite",
                reason="No significant composite drift",
            )

        if result.severity == "significant":
            return EvolutionDecision(
                action="accept",
                trait="composite",
                reason=f"Significant composite drift (score={result.composite_score:.2f})",
            )

        # Notable — defer for review
        return EvolutionDecision(
            action="defer",
            trait="composite",
            reason=f"Notable composite drift (score={result.composite_score:.2f}), flagged for review",
        )

    async def apply(self, decision: EvolutionDecision) -> None:
        """Apply decision: correct via update_traits, log to storage, fire event hook."""
        if decision.action == "correct" and decision.correction_value is not None:
            from alive_memory.identity.self_model import update_traits

            await update_traits(
                self._storage, {decision.trait: decision.correction_value}
            )

        self._updates_this_sleep += 1

        # Log to storage
        await self._storage.log_evolution_decision({
            "id": str(uuid.uuid4()),
            "action": decision.action,
            "trait": decision.trait,
            "reason": decision.reason,
            "correction_value": decision.correction_value,
            "sustained_cycles": decision.sustained_cycles,
        })

        # Fire event hook
        if self._on_decision:
            await self._on_decision(decision)

    def reset_sleep_counter(self) -> None:
        """Call at start of each sleep cycle."""
        self._updates_this_sleep = 0


# ── Backward-compatible free functions ────────────────────────────


async def evaluate_drift(
    report: DriftReport,
    storage: BaseStorage,
    *,
    protected_traits: dict[str, tuple[float, float]] | None = None,
    config: Any | None = None,
) -> EvolutionDecision:
    """Evaluate a drift report (backward compat).

    Creates an IdentityEvolution with GuardRailConfig from protected_traits.
    """
    guard_rails = GuardRailConfig(protected_traits=protected_traits or {})
    evo = IdentityEvolution(storage, guard_rails=guard_rails)
    return await evo.evaluate(report)


async def apply_decision(
    decision: EvolutionDecision,
    storage: BaseStorage,
) -> None:
    """Apply an evolution decision (backward compat)."""
    if decision.action == "correct" and decision.correction_value is not None:
        from alive_memory.identity.self_model import update_traits

        await update_traits(storage, {decision.trait: decision.correction_value})
