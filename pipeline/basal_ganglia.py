"""Basal Ganglia — action selection and gating.

Phase 1: STUB. Wraps validator-approved actions as a single MotorPlan.
All gates return approved. No filtering.

Phase 2 will add: multi-intention selection, energy gating, cooldown
enforcement, suppression logging.
Phase 3 will add: inhibition (Gate 6).
Phase 4 will add: habit shortcuts.
"""

from models.pipeline import (
    ValidatedOutput, ActionDecision, MotorPlan,
)
from models.state import DrivesState


async def select_actions(validated: ValidatedOutput, drives: DrivesState) -> MotorPlan:
    """Select which actions fire this cycle.

    Phase 1 stub: wraps all approved actions into a MotorPlan unchanged.
    Dropped actions become suppressed ActionDecisions with the validator's reason.
    """

    # Wrap approved actions as ActionDecisions
    actions = []
    for req in validated.approved_actions:
        actions.append(ActionDecision(
            action=req.type,
            content=req.detail.get('text', ''),
            target=req.detail.get('target'),
            impulse=1.0,
            priority=1.0,
            status='approved',
            suppression_reason=None,
            source='cortex',
        ))

    # Wrap dropped actions as suppressed ActionDecisions
    suppressed = []
    for dropped in validated.dropped_actions:
        suppressed.append(ActionDecision(
            action=dropped.action.type,
            content=dropped.action.detail.get('text', ''),
            target=dropped.action.detail.get('target'),
            impulse=1.0,
            priority=0.0,
            status='suppressed',
            suppression_reason=dropped.reason,
            source='cortex',
        ))

    return MotorPlan(
        actions=actions,
        suppressed=suppressed,
        habit_fired=False,
        energy_budget=drives.energy,
    )
