"""Basal Ganglia — action selection and gating.

Position: after Validator, before Body.
Question it answers: "Which of these intentions should fire, and which should
be suppressed?"

Phase 2: Full selection gates (1-5). Multi-intention input, priority-sorted
output. Phase 3: Gate 6 (learned inhibition). No habits yet (Phase 4).
"""

import json
import random
from collections import Counter

import clock
import db
from models.pipeline import (
    Intention, ValidatedOutput, ActionDecision, MotorPlan, InhibitionCheck,
)
from models.state import DrivesState
from pipeline.action_registry import ACTION_REGISTRY, check_prerequisites


def _calculate_priority(intention: Intention, drives: DrivesState,
                        energy_cost: float) -> float:
    """Priority calculation per body-spec-v2.md §2.2."""
    base = intention.impulse

    # Social drive boosts visitor-directed actions
    if intention.target == 'visitor':
        base += drives.social_hunger * 0.2

    # Low energy dampens costly actions
    if energy_cost > 0.1 and drives.energy < 0.3:
        base *= 0.6

    return min(base, 1.0)


def _matches_pattern(pattern_json: str, context: dict) -> bool:
    """Check if a stored inhibition pattern matches the current context.

    Pattern is coarse-grained: mode, visitor_present. Broad matching
    ensures inhibitions generalize rather than being too specific.
    """
    try:
        pattern = json.loads(pattern_json)
    except (json.JSONDecodeError, TypeError):
        return True  # malformed pattern → match conservatively

    # Each key in the pattern must match the context
    for key, val in pattern.items():
        if key not in context:
            continue  # missing context key = don't filter on it
        if context[key] != val:
            return False
    return True


async def _check_inhibition(action_name: str, context: dict) -> InhibitionCheck:
    """Gate 6: Check if any learned inhibition applies. Pure DB lookup."""
    try:
        inhibitions = await db.get_inhibitions_for_action(action_name)
    except Exception:
        return InhibitionCheck()  # graceful degradation

    for inhib in inhibitions:
        if inhib['strength'] < 0.2:
            continue  # too weak to matter

        if not _matches_pattern(inhib['pattern'], context):
            continue

        # Probabilistic — stronger inhibitions suppress more reliably
        if random.random() < inhib['strength']:
            # Update tracking
            try:
                await db.update_inhibition(
                    inhib['id'],
                    last_triggered=clock.now_utc().isoformat(),
                    trigger_count=inhib['trigger_count'] + 1,
                )
            except Exception:
                pass  # tracking failure shouldn't block gating

            return InhibitionCheck(
                suppress=True,
                reason=inhib['reason'],
                inhibition_id=inhib['id'],
            )

    return InhibitionCheck()


async def select_actions(validated: ValidatedOutput, drives: DrivesState,
                         context: dict = None) -> MotorPlan:
    """Select which intentions fire this cycle.

    Processes validated.intentions through 6 gates. Actions that pass all
    gates are sorted by priority. Actions rejected at any gate are logged
    as suppressed with reason.

    Falls back to Phase 1 behavior (approved_actions passthrough) when no
    intentions are present, for backward compatibility.
    """
    if context is None:
        context = {}

    intentions = validated.intentions

    # ── Backward compat: no intentions → Phase 1 passthrough ──
    if not intentions:
        return _phase1_passthrough(validated, drives)

    decisions = []
    energy_remaining = drives.energy

    for intention in intentions:
        action_name = intention.action
        decision = ActionDecision(
            action=action_name,
            content=intention.content,
            target=intention.target,
            impulse=intention.impulse,
            priority=0.0,
            status='pending',
            suppression_reason=None,
            source='cortex',
        )

        # Gate 1: Does she know this action?
        if action_name not in ACTION_REGISTRY:
            decision.status = 'incapable'
            decision.suppression_reason = f'Unknown action: {action_name}'
            decisions.append(decision)
            continue

        capability = ACTION_REGISTRY[action_name]

        # Gate 2: Is it enabled?
        if not capability.enabled:
            decision.status = 'incapable'
            decision.suppression_reason = 'Cannot do this yet'
            decisions.append(decision)
            continue

        # Gate 3: Prerequisites met?
        prereq = check_prerequisites(capability.requires, context)
        if not prereq.passed:
            decision.status = 'suppressed'
            decision.suppression_reason = f'Not possible right now: {prereq.failed}'
            decisions.append(decision)
            continue

        # Gate 4: Cooldown
        if capability.last_used and capability.cooldown_seconds > 0:
            elapsed = (clock.now_utc() - capability.last_used).total_seconds()
            if elapsed < capability.cooldown_seconds:
                remaining = int(capability.cooldown_seconds - elapsed)
                decision.status = 'deferred'
                decision.suppression_reason = f'Too soon ({remaining}s remaining)'
                decisions.append(decision)
                continue

        # Gate 5: Energy
        if energy_remaining < capability.energy_cost:
            decision.status = 'suppressed'
            decision.suppression_reason = (
                f'Too tired (need {capability.energy_cost:.2f}, '
                f'have {energy_remaining:.2f})'
            )
            decisions.append(decision)
            continue

        # Gate 6: Inhibition (learned from experience)
        inhibition = await _check_inhibition(action_name, context)
        if inhibition.suppress:
            decision.status = 'inhibited'
            decision.suppression_reason = f'Learned: {inhibition.reason}'
            decisions.append(decision)
            continue

        # Passed all gates — calculate priority
        decision.priority = _calculate_priority(
            intention, drives, capability.energy_cost
        )
        decision.status = 'approved'
        decision.detail = _find_matching_detail(action_name, validated)
        decisions.append(decision)

    # Sort approved by priority descending
    approved = [d for d in decisions if d.status == 'approved']
    approved.sort(key=lambda d: d.priority, reverse=True)

    # Enforce max_per_cycle limits
    approved = _enforce_limits(approved)

    # Deduct energy for approved actions
    for d in approved:
        cap = ACTION_REGISTRY.get(d.action)
        if cap:
            energy_remaining -= cap.energy_cost

    suppressed = [d for d in decisions if d.status != 'approved']

    # Also include validator-dropped actions as suppressed
    for dropped in validated.dropped_actions:
        suppressed.append(ActionDecision(
            action=dropped.action.type,
            content=dropped.action.detail.get('text', ''),
            target=dropped.action.detail.get('target'),
            impulse=1.0,
            priority=0.0,
            status='suppressed',
            suppression_reason=f'Validator: {dropped.reason}',
            source='cortex',
        ))

    return MotorPlan(
        actions=approved,
        suppressed=suppressed,
        habit_fired=False,
        energy_budget=energy_remaining,
    )


def _find_matching_detail(action_name: str, validated: ValidatedOutput) -> dict:
    """Find the original ActionRequest detail dict for this action.

    Consumes matched requests from approved_actions so each intention
    gets a unique detail dict (fixes duplicate action type matching).
    """
    for i, req in enumerate(validated.approved_actions):
        if req.type == action_name:
            validated.approved_actions.pop(i)
            return req.detail
    # Also check full actions list as fallback
    for req in validated.actions:
        if req.type == action_name:
            return req.detail
    return {}


def _enforce_limits(approved: list[ActionDecision]) -> list[ActionDecision]:
    """Enforce max_per_cycle limits. Keep highest-priority per action type."""
    counts: Counter = Counter()
    result = []
    for d in approved:
        cap = ACTION_REGISTRY.get(d.action)
        max_allowed = cap.max_per_cycle if cap else 1
        if counts[d.action] < max_allowed:
            result.append(d)
            counts[d.action] += 1
        else:
            d.status = 'suppressed'
            d.suppression_reason = f'Limit reached ({max_allowed} per cycle)'
    return result


def _phase1_passthrough(validated: ValidatedOutput,
                        drives: DrivesState) -> MotorPlan:
    """Phase 1 backward compat: wrap approved_actions as MotorPlan unchanged."""
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
            detail=req.detail,
        ))

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
