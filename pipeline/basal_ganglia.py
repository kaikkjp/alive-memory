"""Basal Ganglia — action selection and gating.

Position: after Validator, before Body.
Question it answers: "Which of these intentions should fire, and which should
be suppressed?"

Phase 2: Full selection gates (1-5). Multi-intention input, priority-sorted
output. Phase 3: Gate 6 (learned inhibition). Phase 3b (TASK-014):
Visitor-directed priority modulation — trust, interest, drive-based selection
when multiple visitors are present. Phase 4 (TASK-011b): Habit auto-fire —
strong habits bypass cortex entirely.
"""

import json
import random
from collections import Counter

import clock
import db
from models.pipeline import (
    Intention, ValidatedOutput, ActionDecision, MotorPlan, InhibitionCheck,
)
from models.state import DrivesState, EngagementState
from pipeline.action_registry import ACTION_REGISTRY, check_prerequisites
from pipeline.context_bands import compute_trigger_context


# ── Trust-based priority boost for visitor-directed actions ──
_TRUST_PRIORITY_BONUS = {
    'stranger': 0.0,
    'returner': 0.05,
    'regular': 0.10,
    'familiar': 0.15,
}


def _is_visitor_target(target: str | None) -> tuple[bool, str | None]:
    """Parse a target string into (is_visitor, visitor_id).

    Returns:
        (True, 'v1')  for 'visitor:v1'
        (True, None)  for 'visitor'
        (False, None) for anything else (shelf, journal, self, None, etc.)
    """
    if not target:
        return (False, None)
    if target.startswith('visitor:'):
        return (True, target.split(':', 1)[1])
    if target == 'visitor':
        return (True, None)
    return (False, None)


def _calculate_priority(intention: Intention, drives: DrivesState,
                        energy_cost: float, context: dict = None) -> float:
    """Priority calculation per body-spec-v2.md §2.2.

    Phase 3b: visitor-directed priority modulated by trust, interest, and
    competing drives. When multiple visitors are present, this determines
    who she addresses.
    """
    if context is None:
        context = {}

    base = intention.impulse
    is_visitor, visitor_id = _is_visitor_target(intention.target)

    if is_visitor:
        # Social drive boosts visitor-directed actions (increased from 0.2)
        base += drives.social_hunger * 0.3

        # Trust boost — familiar faces pull harder
        visitor_trust = context.get('visitor_trust', {})
        if visitor_id and visitor_id in visitor_trust:
            trust_level = visitor_trust[visitor_id]
        else:
            trust_level = 'stranger'
        base += _TRUST_PRIORITY_BONUS.get(trust_level, 0.0)

        # Conversation interest — questions, gifts, personal content
        visitor_features = context.get('visitor_features', {})
        if visitor_id and visitor_id in visitor_features:
            feats = visitor_features[visitor_id]
            if feats.get('contains_question') or feats.get('contains_gift') \
                    or feats.get('contains_personal_question'):
                base += 0.1

        # Active disengagement — if she's absorbed and conversation is dull
        if drives.expression_need > 0.7 and intention.impulse < 0.4:
            base *= 0.5

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


async def check_habits(drives: DrivesState,
                       engagement: EngagementState) -> MotorPlan | None:
    """Check if a strong habit should auto-fire, bypassing cortex.

    Called BEFORE cortex. If a habit matches the current context with
    strength >= 0.6, returns a single-action MotorPlan directly.
    Cortex is skipped entirely — this is reflex, not thought.

    Returns None if no habit qualifies, letting the normal pipeline proceed.
    """
    ctx = compute_trigger_context(drives, engagement)
    trigger_key = ctx.to_key()

    try:
        all_habits = await db.get_all_habits()
    except Exception:
        return None  # graceful degradation

    matches = [h for h in all_habits
               if h['strength'] >= 0.6 and h['trigger_context'] == trigger_key]

    if not matches:
        return None

    strongest = max(matches, key=lambda h: h['strength'])

    return MotorPlan(
        actions=[ActionDecision(
            action=strongest['action'],
            source='habit',
            impulse=strongest['strength'],
            priority=strongest['strength'],
            status='approved',
            detail={},
        )],
        suppressed=[],
        habit_fired=True,
        energy_budget=drives.energy,
    )


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
            intention, drives, capability.energy_cost, context
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
