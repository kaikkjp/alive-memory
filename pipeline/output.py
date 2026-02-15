"""Output processing — post-action feedback loop.

Position: after Body.
Question it answers: "What changed in the world because of what she did?"

Handles: memory consolidation, pool status updates, drive adjustments,
engagement state updates, action logging, suppression reflection seeds,
inhibition formation, metacognitive monitoring.

Phase 2: Action logging, drive adjustments, self-reflection seeds.
Phase 3: Inhibition formation + metacognitive monitor.
Phase 4: Habit pattern tracking — every executed action strengthens habits.
"""

import json
import re

import clock
from models.event import Event
from models.pipeline import (
    ValidatedOutput, MotorPlan, BodyOutput, CycleOutput,
    ActionDecision, SelfConsistencyResult,
)
from pipeline.action_registry import ACTION_REGISTRY
from pipeline.hippocampus_write import hippocampus_consolidate
from pipeline.hypothalamus import clamp
import db


# ── Action-inferred drive effects (TASK-024) ──
# Successful actions inherently satisfy specific drives beyond what
# EXPRESSION_RELIEF in hypothalamus.py already handles.
# Tech debt: when action registry grows, these should pull from
# registry metadata instead of being hardcoded here.
ACTION_DRIVE_EFFECTS = {
    'speak':          {'curiosity': -0.02},      # conversation provides novel input
    'write_journal':  {'curiosity': -0.03},      # journaling processes thoughts
    'post_x_draft':   {'curiosity': -0.02},      # creative output satisfies curiosity
    'rearrange':      {'curiosity': -0.01},      # physical activity, mild curiosity
    'end_engagement': {'rest_need': -0.03, 'energy': +0.02},  # social load lifted
}


# ── Negative feeling patterns for inhibition signal detection ──
# These are matched against internal_monologue to detect self-assessed
# negative outcomes. No LLM call — the cortex already told us.
NEGATIVE_FEELING_PATTERNS = [
    r"shouldn't have",
    r"regret",
    r"too much",
    r"wrong thing to say",
    r"uncomfortable",
    r"pushed too hard",
    r"felt wrong",
    r"wished I hadn't",
]


async def process_output(body_output: BodyOutput, validated: ValidatedOutput,
                         visitor_id: str = None, motor_plan: MotorPlan = None,
                         cycle_id: str = None) -> CycleOutput:
    """Process post-action side effects.

    Memory consolidation, pool updates, drive adjustments, engagement state,
    action logging, suppression reflection seeds, inhibition updates,
    and metacognitive self-consistency checks.
    All within the caller's transaction boundary.
    """
    result = CycleOutput(body_output=body_output, motor_plan=motor_plan)

    # ── Process memory updates ──
    for update in validated.memory_updates:
        try:
            await hippocampus_consolidate(
                {'type': update.type, 'content': update.content},
                visitor_id,
            )
            result.memory_updates_processed += 1
        except Exception as e:
            result.memory_update_failures += 1
            print(f"  [Memory Error] Failed to consolidate {update.type}: {e}")
            await db.append_event(Event(
                event_type='memory_consolidation_failed',
                source='self',
                payload={
                    'update_type': update.type,
                    'error': f"{type(e).__name__}: {e}",
                    'original_update': {'type': update.type, 'content': update.content},
                    'visitor_id': visitor_id,
                },
            ))

    # ── Update pool item status ──
    pool_id = validated.focus_pool_id
    if pool_id:
        has_collection = any(
            u.type == 'collection_add'
            for u in validated.memory_updates
        )
        has_reflection = any(
            u.type in ('journal_entry', 'totem_create', 'totem_update')
            for u in validated.memory_updates
        )
        now = clock.now_utc()
        outcome = None
        if has_collection:
            outcome = 'accepted'
            await db.update_pool_item(pool_id, status='accepted', engaged_at=now)
        elif has_reflection:
            outcome = 'reflected'
            await db.update_pool_item(pool_id, status='reflected', engaged_at=now)

        if outcome:
            result.pool_outcome = outcome
            pool_item = await db.get_pool_item_by_id(pool_id)
            if pool_item and pool_item.get('source_event_id'):
                await db.update_event_outcome(
                    pool_item['source_event_id'], 'engaged', engaged_at=now
                )

    # ── Update drives (resonance + action outcomes + action-inferred relief) ──
    no_actions = not body_output.executed
    no_dialogue = not validated.dialogue or validated.dialogue == '...'
    is_quiet_cycle = no_actions and no_dialogue
    needs_drives = (validated.resonance or body_output.executed
                    or validated.memory_updates or is_quiet_cycle)
    if needs_drives:
        drives = await db.get_drives_state()
        drives_changed = False

        if validated.resonance:
            drives.social_hunger = max(0.0, drives.social_hunger - 0.15)
            drives.energy = min(1.0, drives.energy + 0.05)
            drives.mood_valence = min(1.0, drives.mood_valence + 0.1)
            drives.curiosity = clamp(drives.curiosity - 0.03)  # engaging conversation
            drives_changed = True
            result.resonance_applied = True

        if body_output.executed:
            failures = [r for r in body_output.executed if not r.success]
            successes = [r for r in body_output.executed if r.success]
            if failures:
                drives.mood_valence = max(-1.0, drives.mood_valence - 0.05 * len(failures))
                drives_changed = True
            if successes:
                drives.mood_valence = min(1.0, drives.mood_valence + 0.02 * len(successes))
                drives_changed = True

        # ── Action-inferred drive relief (TASK-024) ──
        # Successful actions satisfy drives beyond mood. This ensures
        # curiosity, rest_need, and energy respond to what she actually did.
        if body_output.executed:
            for action_result in body_output.executed:
                if not action_result.success:
                    continue
                effects = ACTION_DRIVE_EFFECTS.get(action_result.action, {})
                for field_name, delta in effects.items():
                    current = getattr(drives, field_name)
                    setattr(drives, field_name, clamp(current + delta))
                    drives_changed = True

        # Content engagement satisfies curiosity
        if validated.memory_updates:
            drives.curiosity = clamp(drives.curiosity - 0.04)
            drives_changed = True

        # Quiet cycles (no actions, no dialogue) provide mild rest
        if is_quiet_cycle:
            drives.rest_need = clamp(drives.rest_need - 0.03)
            drives.energy = clamp(drives.energy + 0.02)
            drives_changed = True

        if drives_changed:
            await db.save_drives_state(drives)
            print(f"  [Output] Drives saved: soc={drives.social_hunger:.2f} "
                  f"cur={drives.curiosity:.2f} exp={drives.expression_need:.2f} "
                  f"rest={drives.rest_need:.2f} nrg={drives.energy:.2f} "
                  f"val={drives.mood_valence:.2f}")

    # ── Update engagement state ──
    # Engagement is set when she speaks, not when a visitor connects.
    # This lets the pipeline decide whether to engage (TASK-012).
    dialogue = validated.dialogue
    ending = any(
        d.action == 'end_engagement'
        for d in (motor_plan.actions if motor_plan else [])
    ) or any(
        a.type == 'end_engagement'
        for a in validated.approved_actions
    )
    if visitor_id and dialogue and dialogue != '...' and not ending:
        engagement = await db.get_engagement_state()
        now = clock.now_utc()
        if engagement.status != 'engaged' or engagement.visitor_id != visitor_id:
            # First speak to this visitor — begin engagement
            await db.update_engagement_state(
                status='engaged',
                visitor_id=visitor_id,
                started_at=now,
                last_activity=now,
                turn_count=1,
            )
            # Sync visitor presence: new target → in_conversation,
            # previous target (if any) → waiting
            if engagement.status == 'engaged' and engagement.visitor_id and engagement.visitor_id != visitor_id:
                await db.update_visitor_present(engagement.visitor_id, status='waiting')
            await db.update_visitor_present(visitor_id, status='in_conversation', last_activity=now)
        else:
            # Continuing conversation — update activity and increment turn
            await db.update_engagement_state(
                last_activity=now,
                turn_count=engagement.turn_count + 1,
            )
            # Sync visitor presence: update last activity
            await db.update_visitor_present(visitor_id, last_activity=now)

    # ── Log actions to action_log (Phase 2) ──
    if motor_plan and cycle_id:
        await _log_motor_plan(motor_plan, body_output, cycle_id)

    # ── Suppression reflection seed (Phase 2) ──
    if motor_plan:
        await _inject_reflection_seed(motor_plan)

    # ── Inhibition updates (Phase 3) ──
    if motor_plan and body_output.executed:
        cortex_feelings = validated.internal_monologue or ''
        await _update_inhibitions(motor_plan, body_output, cortex_feelings)

    # ── Habit tracking (Phase 4) ──
    if motor_plan and body_output.executed:
        await _track_action_patterns(motor_plan, body_output)

    # ── Metacognitive monitor (Phase 3) ──
    consistency = await _check_self_consistency(validated)
    if not consistency.consistent:
        await _emit_internal_conflict(consistency, validated)

    return result


async def _log_motor_plan(motor_plan: MotorPlan, body_output: BodyOutput,
                          cycle_id: str) -> None:
    """Log all action decisions (approved + suppressed) and execution results."""
    try:
        # Log approved actions with execution results
        for i, decision in enumerate(motor_plan.actions):
            cap = ACTION_REGISTRY.get(decision.action)
            energy_cost = cap.energy_cost if cap else None

            # Match with execution result if available
            exec_result = None
            if i < len(body_output.executed):
                exec_result = body_output.executed[i]

            await db.log_action(
                cycle_id=cycle_id,
                action=decision.action,
                status='executed' if exec_result else 'approved',
                source=decision.source,
                impulse=decision.impulse,
                priority=decision.priority,
                content=decision.content or None,
                target=decision.target,
                suppression_reason=None,
                energy_cost=energy_cost,
                success=exec_result.success if exec_result else None,
                error=exec_result.error if exec_result else None,
            )

        # Log suppressed actions
        for decision in motor_plan.suppressed:
            cap = ACTION_REGISTRY.get(decision.action)
            energy_cost = cap.energy_cost if cap else None
            await db.log_action(
                cycle_id=cycle_id,
                action=decision.action,
                status=decision.status,
                source=decision.source,
                impulse=decision.impulse,
                priority=decision.priority,
                content=decision.content or None,
                target=decision.target,
                suppression_reason=decision.suppression_reason,
                energy_cost=energy_cost,
                success=None,
                error=None,
            )
    except Exception as e:
        print(f"  [ActionLog] Failed to log actions: {e}")


async def _inject_reflection_seed(motor_plan: MotorPlan) -> None:
    """If a high-impulse action was suppressed, inject a self-reflection seed.

    This goes into the inbox so next cycle's cortex can journal about
    "what I almost did."
    """
    interesting = [s for s in motor_plan.suppressed if s.impulse > 0.5]
    if not interesting:
        return

    strongest = max(interesting, key=lambda s: s.impulse)
    try:
        await db.append_event(Event(
            event_type='self_reflection_seed',
            source='self',
            payload={
                'suppressed_action': strongest.action,
                'suppressed_content': strongest.content,
                'suppressed_target': strongest.target,
                'impulse': strongest.impulse,
                'reason': strongest.suppression_reason,
            },
        ))
    except Exception as e:
        print(f"  [ReflectionSeed] Failed to inject: {e}")


# ── Inhibition system (Phase 3) ──

def _detect_negative_signal(cortex_feelings: str) -> bool:
    """Detect negative outcome signals from cortex internal monologue.

    Internal signals: pattern match on feelings the cortex expressed.
    External signals (visitor left quickly) require heartbeat.py changes
    and will be added in a future task.
    """
    for pattern in NEGATIVE_FEELING_PATTERNS:
        if re.search(pattern, cortex_feelings, re.IGNORECASE):
            return True
    return False


def _detect_positive_signal(action_result) -> bool:
    """Detect positive outcome signals from action results."""
    # Journal write completed (expression is healthy)
    if action_result.action in ('write_journal',) and action_result.success:
        return True
    return False


def _build_inhibition_pattern(decision: ActionDecision) -> str:
    """Build coarse-grained context pattern for inhibition matching.

    Deliberately broad so inhibitions generalize. Only includes fields
    we can reliably determine from the action itself — mode is not
    available here (would require heartbeat context), so we omit it
    to ensure patterns match in _matches_pattern().
    """
    return json.dumps({
        'visitor_present': decision.target == 'visitor',
    })


async def _update_inhibitions(motor_plan: MotorPlan, body_output: BodyOutput,
                              cortex_feelings: str) -> None:
    """Check executed actions for negative/positive signals and form/weaken inhibitions."""
    try:
        negative = _detect_negative_signal(cortex_feelings)

        for action_result in body_output.executed:
            positive = _detect_positive_signal(action_result)

            # Find the matching decision from motor_plan
            decision = None
            for d in motor_plan.actions:
                if d.action == action_result.action:
                    decision = d
                    break
            if not decision:
                continue

            await _maybe_form_inhibition(decision, negative, positive)
    except Exception as e:
        print(f"  [Inhibition] Error updating inhibitions: {e}")


async def _maybe_form_inhibition(decision: ActionDecision,
                                 negative: bool, positive: bool) -> None:
    """Form, strengthen, or weaken inhibitions based on signals."""
    pattern_json = _build_inhibition_pattern(decision)

    if negative:
        existing = await db.find_matching_inhibition(decision.action, pattern_json)
        if existing:
            new_strength = min(existing['strength'] + 0.15, 1.0)
            await db.update_inhibition(
                existing['id'],
                strength=new_strength,
                trigger_count=existing['trigger_count'] + 1,
            )
        else:
            reason_seed = json.dumps({
                'action': decision.action,
                'target': decision.target,
                'trigger': 'self_assessment',
            })
            await db.create_inhibition(
                action=decision.action,
                pattern=pattern_json,
                reason=reason_seed,
                strength=0.3,
            )

    elif positive:
        existing = await db.find_matching_inhibition(decision.action, pattern_json)
        if existing:
            new_strength = max(existing['strength'] - 0.1, 0.0)
            if new_strength < 0.05:
                await db.delete_inhibition(existing['id'])
            else:
                await db.update_inhibition(existing['id'], strength=new_strength)


# ── Habit tracking (Phase 4) ──

HABIT_STRENGTH_CAP = 0.9


def _habit_delta(current_strength: float) -> float:
    """Piecewise strength increment: fast 0→0.4, medium 0.4→0.6, slow 0.6+."""
    if current_strength < 0.4:
        return 0.12
    elif current_strength < 0.6:
        return 0.06
    else:
        return 0.03


async def _track_action_patterns(motor_plan: MotorPlan,
                                  body_output: BodyOutput) -> None:
    """Track every executed action as a habit pattern.

    Called after every cycle. Strengthens existing habits or creates new ones.
    Piecewise curve: fast 0→0.4, medium 0.4→0.6, slow 0.6→0.9.
    """
    try:
        from pipeline.context_bands import compute_trigger_context

        drives = await db.get_drives_state()
        engagement = await db.get_engagement_state()
        ctx = compute_trigger_context(drives, engagement)
        trigger_key = ctx.to_key()

        for action_result in body_output.executed:
            if not action_result.success:
                continue

            # Find matching decision from motor_plan
            decision = None
            for d in motor_plan.actions:
                if d.action == action_result.action:
                    decision = d
                    break
            if not decision:
                continue

            await _track_single_action(decision.action, trigger_key)
    except Exception as e:
        print(f"  [HabitTrack] Error tracking action patterns: {e}")


async def _track_single_action(action: str, trigger_key: str) -> None:
    """Track a single action — strengthen existing habit or create new one."""
    existing = await db.find_matching_habit(action, trigger_key)
    if existing:
        new_count = existing['repetition_count'] + 1
        new_strength = min(HABIT_STRENGTH_CAP,
                           existing['strength'] + _habit_delta(existing['strength']))
        await db.update_habit(
            existing['id'],
            strength=new_strength,
            repetition_count=new_count,
            last_triggered=clock.now_utc(),
        )
    else:
        await db.create_habit(action, trigger_key, strength=0.1)


# ── Metacognitive monitor (Phase 3) ──

async def _check_self_consistency(validated: ValidatedOutput) -> SelfConsistencyResult:
    """Compare executed output against voice rules and physical traits.

    Detects inconsistencies AFTER the fact — does not prevent them.
    Divergences become internal_conflict events for reflection.
    """
    from config.identity import VOICE_RULES_PATTERNS, PHYSICAL_TRAITS_PATTERNS

    conflicts = []
    dialogue = validated.dialogue or ''

    if not dialogue or dialogue == '...':
        return SelfConsistencyResult()

    # Check physical trait contradictions
    for pattern, desc in PHYSICAL_TRAITS_PATTERNS:
        if pattern.search(dialogue):
            conflicts.append(desc)

    # Check voice rule: no laughter
    if VOICE_RULES_PATTERNS['no_laughter'].search(dialogue):
        conflicts.append("Used 'haha/lol' instead of describing the feeling")

    # Check voice rule: no exclamation unless surprised
    if validated.expression != 'surprised' and '!' in dialogue:
        conflicts.append("Used exclamation mark without being surprised")

    return SelfConsistencyResult(
        consistent=len(conflicts) == 0,
        conflicts=conflicts,
    )


async def _emit_internal_conflict(consistency: SelfConsistencyResult,
                                  validated: ValidatedOutput) -> None:
    """Emit an internal_conflict event to inbox for next cycle's reflection."""
    try:
        conflict_desc = '; '.join(consistency.conflicts)
        await db.append_event(Event(
            event_type='internal_conflict',
            source='self',
            payload={
                'conflicts': consistency.conflicts,
                'dialogue_excerpt': (validated.dialogue or '')[:200],
                'expression': validated.expression,
                'description': conflict_desc,
            },
        ))
        print(f"  [Metacognitive] Internal conflict detected: {conflict_desc}")
    except Exception as e:
        print(f"  [Metacognitive] Failed to emit conflict: {e}")
