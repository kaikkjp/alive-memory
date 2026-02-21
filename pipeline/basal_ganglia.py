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
from db.parameters import p
from models.pipeline import (
    Intention, ValidatedOutput, ActionDecision, MotorPlan, InhibitionCheck,
    HabitBoost,
)
from models.state import DrivesState, EngagementState
from pipeline.action_registry import ACTION_REGISTRY, check_prerequisites
from pipeline.context_bands import compute_trigger_context


# ── Trust-based priority boost: loaded from self_parameters at call time ──
_TRUST_LEVELS = ('stranger', 'returner', 'regular', 'familiar')


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
                        context: dict = None) -> float:
    """Priority calculation per body-spec-v2.md S2.2.

    Phase 3b: visitor-directed priority modulated by trust, interest, and
    competing drives. When multiple visitors are present, this determines
    who she addresses.
    """
    if context is None:
        context = {}

    base = intention.impulse
    is_visitor, visitor_id = _is_visitor_target(intention.target)

    if is_visitor:
        # Social drive boosts visitor-directed actions
        base += drives.social_hunger * p('basal_ganglia.priority.social_hunger_factor')

        # Trust boost — familiar faces pull harder
        visitor_trust = context.get('visitor_trust', {})
        if visitor_id and visitor_id in visitor_trust:
            trust_level = visitor_trust[visitor_id]
        else:
            trust_level = 'stranger'
        if trust_level in _TRUST_LEVELS:
            base += p(f'basal_ganglia.trust_bonus.{trust_level}')
        # unknown trust_level -> no bonus (0.0)

        # Conversation interest — questions, gifts, personal content
        visitor_features = context.get('visitor_features', {})
        if visitor_id and visitor_id in visitor_features:
            feats = visitor_features[visitor_id]
            if feats.get('contains_question') or feats.get('contains_gift') \
                    or feats.get('contains_personal_question'):
                base += p('basal_ganglia.priority.interest_bonus')

        # Active disengagement — if she's absorbed and conversation is dull
        if drives.expression_need > 0.7 and intention.impulse < 0.4:
            base *= p('basal_ganglia.priority.disengagement_factor')

    return min(base, 1.0)


def _matches_pattern(pattern_json: str, context: dict) -> bool:
    """Check if a stored inhibition pattern matches the current context.

    Pattern is coarse-grained: mode, visitor_present. Broad matching
    ensures inhibitions generalize rather than being too specific.
    """
    try:
        pattern = json.loads(pattern_json)
    except (json.JSONDecodeError, TypeError):
        return True  # malformed pattern -> match conservatively

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
        if inhib['strength'] < p('basal_ganglia.inhibition.strength_threshold'):
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


# ── Drive gates for habit auto-fire ──
# Habits should only fire when the relevant drive supports the action.
# Without this, write_journal fires every cycle and drains curiosity to 0.
# NOTE: This is a structural mapping (action -> (drive_field, threshold)).
# The open_shop rest gate is evaluated at check time via p().
HABIT_DRIVE_GATES: dict[str, tuple[str, float]] = {
    'write_journal':   ('expression_need', 0.2),
    'express_thought': ('expression_need', 0.2),
    'post_x_draft':    ('expression_need', 0.2),
    'speak':           ('social_hunger', 0.3),
    'rearrange':       ('energy', 0.3),
    'place_item':      ('energy', 0.3),
    'open_shop':       ('energy', 0.3),
    'close_shop':      ('rest_need', 0.0),  # always allowed by drive; gated by shop status
}

# Backward-compat export (used by tests/test_habits.py).
# Actual logic reads from p('basal_ganglia.habit.cooldown_cycles').
HABIT_COOLDOWN_CYCLES = 3

_habit_fire_history: dict[str, int] = {}  # action -> cycle_number of last fire
_habit_cycle_counter: int = 0


def _passes_drive_gate(action: str, drives: DrivesState) -> bool:
    """Check if the relevant drive supports this habit firing."""
    gate = HABIT_DRIVE_GATES.get(action)
    if gate is None:
        return True  # no gate defined -> always allowed
    field, threshold = gate
    if not getattr(drives, field) > threshold:
        return False
    # Composite gate: open_shop also requires rest_need below threshold
    if action == 'open_shop' and drives.rest_need >= p('basal_ganglia.habit.open_shop_rest_gate'):
        return False
    return True


async def _passes_shop_gate(action: str) -> bool:
    """Check context gates that require DB lookups (e.g. shop status)."""
    if action == 'close_shop':
        try:
            room = await db.get_room_state()
            return room.shop_status == 'open'
        except Exception:
            return False  # can't verify -> don't fire
    if action == 'open_shop':
        try:
            room = await db.get_room_state()
            return room.shop_status == 'closed'
        except Exception:
            return False  # can't verify -> don't fire
    return True


def _passes_cooldown_gate(action: str) -> bool:
    """Check if enough cycles have passed since last habit-fire of this action."""
    last_fire = _habit_fire_history.get(action)
    if last_fire is None:
        return True
    return (_habit_cycle_counter - last_fire) >= int(p('basal_ganglia.habit.cooldown_cycles'))


def _record_habit_fire(action: str) -> None:
    """Record that this action habit-fired on the current cycle."""
    _habit_fire_history[action] = _habit_cycle_counter


async def check_habits(drives: DrivesState,
                       engagement: EngagementState) -> MotorPlan | HabitBoost | None:
    """Check if a strong habit should fire.

    Called BEFORE cortex. If a habit matches the current context with
    strength >= habit.strength_threshold AND passes drive/cooldown gates:
    - Reflexive action (generative=False): returns MotorPlan directly.
      Cortex is skipped entirely — reflex, not thought.
    - Generative action (generative=True): returns HabitBoost.
      Cortex still runs, but the habit nudges impulse (+0.3) for that action.

    Returns None if no habit qualifies, letting the normal pipeline proceed.
    """
    global _habit_cycle_counter
    _habit_cycle_counter += 1

    ctx = compute_trigger_context(drives, engagement)
    trigger_key = ctx.to_key()

    try:
        all_habits = await db.get_all_habits()
    except Exception:
        return None  # graceful degradation

    habit_threshold = p('basal_ganglia.habit.strength_threshold')
    matches = [h for h in all_habits
               if h['strength'] >= habit_threshold and h['trigger_context'] == trigger_key]

    if not matches:
        return None

    # Sort by strength descending, try each until one passes all gates
    matches.sort(key=lambda h: h['strength'], reverse=True)

    for habit in matches:
        action = habit['action']

        # Gate: drive state must support this action
        if not _passes_drive_gate(action, drives):
            continue

        # Gate: per-action cooldown (safety net against rapid re-fire)
        if not _passes_cooldown_gate(action):
            continue

        # Gate: context checks requiring DB (e.g. shop must be open)
        if not await _passes_shop_gate(action):
            continue

        # All gates passed — record fire and return
        _record_habit_fire(action)

        cap = ACTION_REGISTRY.get(action)
        if cap and cap.generative:
            return HabitBoost(
                action=action,
                strength=habit['strength'],
                habit_id=habit['id'],
            )

        return MotorPlan(
            actions=[ActionDecision(
                action=action,
                source='habit',
                impulse=habit['strength'],
                priority=habit['strength'],
                status='approved',
                detail={},
            )],
            suppressed=[],
            habit_fired=True,
        )

    return None  # all matching habits gated out


async def _resolve_dynamic_action(action_name: str, decision: ActionDecision) -> str | None:
    """Resolve an unknown action via the dynamic actions table.

    Returns:
        'alias'      — action was an alias; decision.action updated to target
        'body_state' — action is a body state update; decision auto-approved
        None         — action recorded as pending; decision marked incapable
    """
    dyn = await db.get_dynamic_action(action_name)

    if dyn is None:
        # Never seen before — record it
        await db.record_unknown_action(action_name)
        decision.status = 'incapable'
        decision.suppression_reason = f'Unknown action: {action_name} (recorded as pending)'
        return None

    if dyn['status'] == 'alias' and dyn['alias_for']:
        # Redirect to the aliased action
        target = dyn['alias_for']
        if target in ACTION_REGISTRY and ACTION_REGISTRY[target].enabled:
            decision.action = target
            decision.detail['_original_action'] = action_name
            return 'alias'
        else:
            decision.status = 'incapable'
            decision.suppression_reason = f'Alias {action_name}→{target} but target disabled'
            return None

    if dyn['status'] == 'body_state' and dyn['body_state']:
        # Auto-approve as body state change
        decision.status = 'approved'
        decision.detail['_body_state_update'] = dyn['body_state']
        decision.detail['_original_action'] = action_name
        return 'body_state'

    # Pending or rejected — increment count, stay incapable
    await db.record_unknown_action(action_name)  # bumps attempt_count
    decision.status = 'incapable'
    decision.suppression_reason = f'Unknown action: {action_name} (seen {dyn["attempt_count"] + 1}x, pending review)'
    return None


async def _has_reflection_evidence() -> bool:
    """Check if the Shopkeeper has journaled very recently (last 3 events).

    v1 heuristic: tight window — journal must be one of the last 3 events.
    TECH DEBT: thread cycle_id through here and require same-cycle reflection.
    """
    import db as _db  # local import to avoid circular
    recent = await _db.get_recent_events(limit=3)
    for ev in recent:
        if ev.event_type == 'action_journal':
            return True
    return False


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

    # ── Backward compat: no intentions -> Phase 1 passthrough ──
    if not intentions:
        return _phase1_passthrough(validated, drives)

    decisions = []

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

        # Gate 1: Action resolution — static → dynamic alias → body_state → pending
        if action_name not in ACTION_REGISTRY:
            resolved = await _resolve_dynamic_action(action_name, decision)
            if resolved is None:
                # Truly unknown — recorded as pending, marked incapable
                decisions.append(decision)
                continue
            elif resolved == 'alias':
                # Swap action_name to the alias target, continue through gates
                action_name = decision.action  # updated by _resolve_dynamic_action
            elif resolved == 'body_state':
                # Body state update — auto-approve, skip remaining gates
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

        # Gate 5: Shop status prerequisite (open_shop/close_shop)
        if not await _passes_shop_gate(action_name):
            decision.status = 'suppressed'
            if action_name == 'open_shop':
                decision.suppression_reason = 'Shop is already open'
            elif action_name == 'close_shop':
                decision.suppression_reason = 'Shop is already closed'
            else:
                decision.suppression_reason = 'Shop status check failed'
            decisions.append(decision)
            continue

        # Gate 5b: Drive gates for shop actions
        if action_name == 'open_shop':
            if drives.rest_need >= p('basal_ganglia.habit.open_shop_rest_gate'):
                decision.status = 'suppressed'
                decision.suppression_reason = f'Need rest first (rest_need {drives.rest_need:.2f})'
                decisions.append(decision)
                continue

        # Gate 6: Inhibition (learned from experience)
        inhibition = await _check_inhibition(action_name, context)
        if inhibition.suppress:
            decision.status = 'inhibited'
            decision.suppression_reason = f'Learned: {inhibition.reason}'
            decisions.append(decision)
            continue

        # Gate 7: modify_self requires recent reflection evidence
        if action_name == 'modify_self':
            has_evidence = await _has_reflection_evidence()
            if not has_evidence:
                decision.status = 'suppressed'
                decision.suppression_reason = 'modify_self requires recent reflection (journal within last 3 events)'
                decisions.append(decision)
                continue
            # Validate parameter key and value are present in the ActionRequest detail
            action_detail = {}
            for req in validated.approved_actions:
                if req.type == action_name:
                    action_detail = req.detail
                    break
            if not action_detail:
                for req in validated.actions:
                    if req.type == action_name:
                        action_detail = req.detail
                        break
            param_key = action_detail.get('parameter')
            new_value = action_detail.get('value')
            if not param_key or new_value is None:
                decision.status = 'suppressed'
                decision.suppression_reason = 'modify_self requires parameter and value in detail'
                decisions.append(decision)
                continue

        # Passed all gates — calculate priority
        decision.priority = _calculate_priority(
            intention, drives, context
        )
        decision.status = 'approved'
        # For aliased actions the cortex sent the original name; look up detail
        # by the original action name so the payload (e.g. content_id for
        # read_content) is not lost.  _original_action was stashed by
        # _resolve_dynamic_action when the alias was resolved.
        lookup_name = decision.detail.get('_original_action', action_name)
        fetched_detail = _find_matching_detail(lookup_name, validated)
        # Merge: keep any resolver metadata already on decision.detail, then
        # overlay the fetched request payload so caller fields win.
        decision.detail = {**decision.detail, **fetched_detail}
        _backfill_action_detail(decision)
        decisions.append(decision)

    # Sort approved by priority descending
    approved = [d for d in decisions if d.status == 'approved']
    approved.sort(key=lambda d: d.priority, reverse=True)

    # Enforce max_per_cycle limits
    approved = _enforce_limits(approved)

    suppressed = [d for d in decisions if d.status != 'approved']

    # Also include validator-dropped actions as suppressed
    for dropped in validated.dropped_actions:
        suppressed.append(ActionDecision(
            action=dropped.action.type,
            content=dropped.action.detail.get('text', ''),
            target=dropped.action.detail.get('target'),
            impulse=_lookup_impulse(dropped.action.type, validated),
            priority=0.0,
            status='suppressed',
            suppression_reason=f'Validator: {dropped.reason}',
            source='cortex',
        ))

    return MotorPlan(
        actions=approved,
        suppressed=suppressed,
        habit_fired=False,
    )


def _lookup_impulse(action_name: str, validated: ValidatedOutput) -> float:
    """Find the cortex-specified impulse for a dropped action.

    Searches intentions first (Phase 2 format), falls back to 0.5
    (the Intention default) if no match — never lies with 1.0.
    """
    for intention in validated.intentions:
        if intention.action == action_name:
            return intention.impulse
    return 0.5


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


def _extract_content_id_from_content(content: str) -> str | None:
    """Extract a content_id token from freeform intention content."""
    raw = (content or '').strip()
    if not raw:
        return None

    lowered = raw.lower()
    if lowered.startswith('content_id:'):
        value = raw.split(':', 1)[1].strip()
        return value or None
    if lowered.startswith('id:'):
        value = raw.split(':', 1)[1].strip()
        return value or None

    return None


def _backfill_action_detail(decision: ActionDecision) -> None:
    """Bridge intention.content into executor-friendly detail keys."""
    content = (decision.content or '').strip()
    if not content:
        return

    detail = decision.detail

    text_actions = {
        'speak', 'write_journal', 'post_x_draft', 'post_x', 'reply_x',
        'post_x_image', 'tg_send', 'express_thought',
    }
    if decision.action in text_actions and not detail.get('text') and not detail.get('content'):
        detail['text'] = content

    if decision.action == 'tg_send_image' and not detail.get('caption'):
        detail['caption'] = content

    content_actions = {'read_content', 'save_for_later', 'mention_in_conversation'}
    if decision.action in content_actions and not detail.get('content_id'):
        content_id = _extract_content_id_from_content(content)
        if content_id:
            detail['content_id'] = content_id


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
            impulse=_lookup_impulse(dropped.action.type, validated),
            priority=0.0,
            status='suppressed',
            suppression_reason=dropped.reason,
            source='cortex',
        ))

    return MotorPlan(
        actions=actions,
        suppressed=suppressed,
        habit_fired=False,
    )
