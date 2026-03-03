"""Identity evolution — three-tier resolution for behavioral changes.

Extracted from engine/identity/evolution.py.
Stripped: hardcoded protection rules.
Kept: accept/correct/defer decision logic, parameterized protection.

Three-tier hierarchy:
  1. Accept — drift is natural growth, allow it
  2. Correct — drift violates a core trait, revert it
  3. Defer — unclear, flag for operator review
"""

from __future__ import annotations

from dataclasses import dataclass

from alive_memory.config import AliveConfig
from alive_memory.identity.drift import DriftReport
from alive_memory.storage.base import BaseStorage


@dataclass
class EvolutionDecision:
    """Result of evaluating a drift report."""
    action: str  # "accept", "correct", "defer"
    trait: str
    reason: str
    correction_value: float | None = None  # only for "correct"


async def evaluate_drift(
    report: DriftReport,
    storage: BaseStorage,
    *,
    protected_traits: dict[str, tuple[float, float]] | None = None,
    config: AliveConfig | None = None,
) -> EvolutionDecision:
    """Evaluate a drift report and decide how to handle it.

    Args:
        report: The detected drift.
        storage: Storage backend.
        protected_traits: Dict of trait_name → (min_bound, max_bound).
            Drift that pushes a trait outside its bounds triggers correction.
        config: Configuration parameters.

    Returns:
        EvolutionDecision with action and reasoning.
    """
    # Check against protected bounds
    if protected_traits and report.trait in protected_traits:
        lo, hi = protected_traits[report.trait]
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

    # High-confidence drift with consistent direction → accept
    if report.confidence > 0.7 and report.magnitude > 0.1:
        return EvolutionDecision(
            action="accept",
            trait=report.trait,
            reason=f"Consistent {report.direction} drift (confidence: {report.confidence:.2f})",
        )

    # Low-confidence or small magnitude → defer
    if report.confidence < 0.4:
        return EvolutionDecision(
            action="defer",
            trait=report.trait,
            reason=f"Low confidence drift ({report.confidence:.2f}), flagged for review",
        )

    # Medium confidence — accept if magnitude is significant
    if report.magnitude > 0.2:
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


async def apply_decision(
    decision: EvolutionDecision,
    storage: BaseStorage,
) -> None:
    """Apply an evolution decision.

    - accept: no action (trait stays as-is)
    - correct: revert trait to correction_value
    - defer: no action (logged for operator review)
    """
    if decision.action == "correct" and decision.correction_value is not None:
        from alive_memory.identity.self_model import update_traits
        await update_traits(storage, {decision.trait: decision.correction_value})
