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
from db.parameters import p
import db


# ── Action-inferred drive effects (TASK-024) ──
# Successful actions inherently satisfy specific drives beyond what
# EXPRESSION_RELIEF in hypothalamus.py already handles.
# Tech debt: when action registry grows, these should pull from
# registry metadata instead of being hardcoded here.
def _build_action_drive_effects() -> dict:
    """Build action drive effects from parameters."""
    return {
        # TASK-044: Removed curiosity drains. Curiosity is stimulus-driven,
        # not drained by actions. Content consumption produces growth, not drain.
        'speak':          {},                          # conversation — no curiosity drain
        'write_journal':  {},                          # journaling — no curiosity drain
        'post_x_draft':   {},                          # creative output — no curiosity drain
        'rearrange':      {},                          # physical activity — no curiosity drain
        'end_engagement': {'rest_need': p('output.drives.end_engagement_rest_relief')},  # social load lifted
    }

# ── X draft limits (TASK-057) ──
X_DRAFT_MAX_CHARS = 280
X_DRAFT_DAILY_CAP = 8
X_DRAFT_COOLDOWN_SECONDS = 1800  # 30 minutes


# ── Negative feeling patterns (reserved for future use) ──
# Patterns for detecting self-assessed negative outcomes from cortex monologue.
# NOT used for inhibition formation — internal self-doubt must not silence
# creative output. Reserved for a future emotional logging feature.
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

# ── Inhibition formation guards ──
# Triggers that must NEVER form inhibitions. All are internal self-doubt signals
# that fire on normal introspection. Checked in _maybe_form_inhibition so the
# guard is enforced at the formation site, not only at the call site.
INHIBITION_BLOCKED_TRIGGERS = {'self_assessment', 'mood_decline', 'repetition'}

# Minimum cycle count before any inhibitions can form.
# She needs time to establish baselines before learning avoidance.
INHIBITION_MIN_CYCLE = 100

# Module-level latch: once we've confirmed cycle_count >= INHIBITION_MIN_CYCLE,
# we skip the DB call on every subsequent cycle.
_inhibition_guard_cleared: bool = False


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
            drives.social_hunger = max(0.0, drives.social_hunger - p('output.resonance.social_relief'))
            drives.mood_valence = min(1.0, drives.mood_valence + p('output.resonance.valence_boost'))
            drives.curiosity = clamp(drives.curiosity - p('output.resonance.curiosity_relief'))  # engaging conversation
            drives.mood_arousal = clamp(drives.mood_arousal + p('output.resonance.arousal_boost'))  # arousal spike
            drives_changed = True
            result.resonance_applied = True

        if body_output.executed:
            failures = [r for r in body_output.executed if not r.success]
            successes = [r for r in body_output.executed if r.success]
            if failures:
                drives.mood_valence = max(-1.0, drives.mood_valence + p('output.drives.failure_valence_penalty') * len(failures))
                drives_changed = True
            if successes:
                # Diminishing mood bonus (TASK-036): emotional habituation
                # First 10 actions: near-full bonus. After 30: ~0.005.
                actions_today_count = await db.get_executed_action_count_today()
                for _ in successes:
                    bonus = p('output.drives.success_bonus_base') / (1 + actions_today_count / p('output.drives.success_habituation_divisor'))
                    drives.mood_valence = min(1.0, drives.mood_valence + bonus)
                    actions_today_count += 1  # each success in this batch counts
                drives_changed = True

        # ── Action-inferred drive relief (TASK-024) ──
        # Successful actions satisfy drives beyond mood. This ensures
        # curiosity, rest_need, and energy respond to what she actually did.
        _ROUTINE_ACTIONS = {'write_journal', 'express_thought'}
        if body_output.executed:
            action_drive_effects = _build_action_drive_effects()
            for action_result in body_output.executed:
                if not action_result.success:
                    continue
                effects = action_drive_effects.get(action_result.action, {})
                for field_name, delta in effects.items():
                    current = getattr(drives, field_name)
                    setattr(drives, field_name, clamp(current + delta))
                    drives_changed = True
                # Non-routine actions bump arousal (novelty/engagement)
                if action_result.action not in _ROUTINE_ACTIONS:
                    drives.mood_arousal = clamp(drives.mood_arousal + p('output.drives.non_routine_arousal_bump'))
                    drives_changed = True

        # TASK-044: Content engagement no longer drains curiosity.
        # Curiosity is stimulus-driven via gap detection. Reading produces
        # growth (memories, questions, mood), not drain.

        # Quiet cycles (no actions, no dialogue) provide mild rest
        if is_quiet_cycle:
            drives.rest_need = clamp(drives.rest_need + p('output.drives.quiet_cycle_rest_relief'))
            drives_changed = True

        if drives_changed:
            await db.save_drives_state(drives)
            print(f"  [Output] Drives saved: soc={drives.social_hunger:.2f} "
                  f"cur={drives.curiosity:.2f} exp={drives.expression_need:.2f} "
                  f"rest={drives.rest_need:.2f} nrg={drives.energy:.2f} "
                  f"val={drives.mood_valence:.2f} aro={drives.mood_arousal:.2f}")

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

    # ── Log self-modifications for operator visibility ──
    for action_result in body_output.executed:
        if action_result.action == 'modify_self' and action_result.success:
            print(f"  [Output] Self-modification: {action_result.payload}")

    # ── Persist X drafts with limits (TASK-057) ──
    if body_output.executed and motor_plan:
        await _persist_x_draft(body_output, motor_plan=motor_plan, cycle_id=cycle_id)

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

    # ── Habit decay (TASK-036) ──
    # Decay habits that didn't fire this cycle. Collect fired actions first.
    fired_this_cycle = set()
    if body_output.executed:
        for ar in body_output.executed:
            if ar.success:
                fired_this_cycle.add(ar.action)
    await _decay_unfired_habits(fired_this_cycle)

    # ── Epistemic curiosity lifecycle (TASK-043) ──
    await _process_epistemic_curiosities(validated, body_output)

    # ── Reflection loop (TASK-044) ──
    await process_reflection(validated, body_output)

    # ── Metacognitive monitor (Phase 3) ──
    consistency = await _check_self_consistency(validated)
    if not consistency.consistent:
        await _emit_internal_conflict(consistency, validated)

    return result


async def _persist_x_draft(body_output: BodyOutput, motor_plan: MotorPlan,
                           cycle_id: str = None) -> None:
    """Intercept post_x_draft results and persist as queued drafts.

    Enforces: 280 char limit, dedup within 24h, daily cap of 8, 30 min cooldown.
    Draft text is extracted from motor_plan (body.py doesn't set result.content).
    """
    for action_result in body_output.executed:
        if action_result.action != 'post_x_draft' or not action_result.success:
            continue

        # Extract draft text from motor plan decision detail
        draft_text = ''
        for decision in motor_plan.actions:
            if decision.action == 'post_x_draft':
                draft_text = (decision.detail.get('text', '') if decision.detail else '').strip()
                break

        if not draft_text:
            print("  [XDraft] No draft text in motor plan, skipping")
            continue

        # ── Char limit ──
        if len(draft_text) > X_DRAFT_MAX_CHARS:
            draft_text = draft_text[:X_DRAFT_MAX_CHARS]
            print(f"  [XDraft] Truncated to {X_DRAFT_MAX_CHARS} chars")

        # ── Dedup check ──
        try:
            is_dup = await db.check_dedup(draft_text)
            if is_dup:
                print("  [XDraft] Duplicate draft rejected (similar within 24h)")
                continue
        except Exception as e:
            print(f"  [XDraft] Dedup check failed: {e}")

        # ── Daily cap ──
        try:
            daily_count = await db.get_daily_post_count()
            if daily_count >= X_DRAFT_DAILY_CAP:
                print(f"  [XDraft] Daily cap reached ({daily_count}/{X_DRAFT_DAILY_CAP})")
                continue
        except Exception as e:
            print(f"  [XDraft] Daily cap check failed: {e}")

        # ── Cooldown ──
        try:
            still_cooling = await db.check_cooldown(X_DRAFT_COOLDOWN_SECONDS)
            if still_cooling:
                print("  [XDraft] Cooldown active (30 min between drafts)")
                continue
        except Exception as e:
            print(f"  [XDraft] Cooldown check failed: {e}")

        # ── Persist ──
        try:
            draft = await db.insert_x_draft(draft_text, cycle_id=cycle_id)
            print(f"  [XDraft] Draft created: {draft['id'][:8]}... ({len(draft_text)} chars)")
        except Exception as e:
            print(f"  [XDraft] Failed to persist draft: {e}")


async def _log_motor_plan(motor_plan: MotorPlan, body_output: BodyOutput,
                          cycle_id: str) -> None:
    """Log all action decisions (approved + suppressed) and execution results."""
    try:
        # Log approved actions with execution results
        for i, decision in enumerate(motor_plan.actions):
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
                energy_cost=None,
                success=exec_result.success if exec_result else None,
                error=exec_result.error if exec_result else None,
            )

        # Log suppressed actions
        for decision in motor_plan.suppressed:
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
                energy_cost=None,
                success=None,
                error=None,
            )
    except Exception as e:
        import traceback
        print(f"  [ActionLog] Failed to log actions: {e}")
        traceback.print_exc()


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

    RESERVED — not used for inhibition formation (TASK-054).
    Internal self-doubt must not silence creative output.
    Future use: emotional logging, reflection seeds, or wellbeing tracking.
    External inhibition signals (visitor_displeasure) are wired separately —
    see future task for heartbeat.py integration.
    """
    for pattern in NEGATIVE_FEELING_PATTERNS:
        if re.search(pattern, cortex_feelings, re.IGNORECASE):
            return True
    return False


def _detect_positive_signal(action_result) -> bool:
    """Detect positive outcome signals from action results."""
    # Journal write completed (expression is healthy) — only if she actually wrote
    if (action_result.action == 'write_journal'
            and action_result.success
            and 'journal_entry_created' in action_result.side_effects):
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
    """Check executed actions for positive signals and weaken inhibitions.

    Self-assessment signals (internal doubt) are excluded from inhibition
    formation — they fire on normal introspection and would silence
    write_journal and express_thought. Only external signals (visitor_displeasure)
    form new inhibitions, enforced via INHIBITION_BLOCKED_TRIGGERS in
    _maybe_form_inhibition. External wiring is a future task.

    Positive signals (write_journal success) always run — existing inhibitions
    can weaken at any cycle, not just after INHIBITION_MIN_CYCLE. The cycle
    guard lives inside _maybe_form_inhibition and blocks formation only.
    """
    try:
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

            # Internal negatives (self_assessment) never form inhibitions —
            # enforced by INHIBITION_BLOCKED_TRIGGERS inside _maybe_form_inhibition.
            # Positive signals weaken existing inhibitions regardless of cycle count.
            await _maybe_form_inhibition(decision, negative=False, positive=positive,
                                         trigger='internal')
    except Exception as e:
        print(f"  [Inhibition] Error updating inhibitions: {e}")


async def _maybe_form_inhibition(decision: ActionDecision,
                                 negative: bool, positive: bool,
                                 trigger: str = 'external') -> None:
    """Form, strengthen, or weaken inhibitions based on signals.

    trigger: label for why the inhibition formed (e.g. 'visitor_displeasure').
    Triggers in INHIBITION_BLOCKED_TRIGGERS are rejected at the formation site,
    providing a safety net even if a caller passes negative=True incorrectly.

    Cycle guard (formation only): no new inhibitions before INHIBITION_MIN_CYCLE.
    Positive weakening always runs — existing inhibitions can decay from cycle 0.
    """
    global _inhibition_guard_cleared
    pattern_json = _build_inhibition_pattern(decision)

    if negative:
        # Hard gate: internal self-doubt triggers must never form inhibitions
        if trigger in INHIBITION_BLOCKED_TRIGGERS:
            return
        # Cycle guard: no formation before baseline is established
        if not _inhibition_guard_cleared:
            cycle_count = await db.count_cycle_logs()
            if cycle_count < INHIBITION_MIN_CYCLE:
                return
            _inhibition_guard_cleared = True
        existing = await db.find_matching_inhibition(decision.action, pattern_json)
        if existing:
            new_strength = min(existing['strength'] + p('output.inhibition.strength_increment'), 1.0)
            await db.update_inhibition(
                existing['id'],
                strength=new_strength,
                trigger_count=existing['trigger_count'] + 1,
            )
        else:
            reason_seed = json.dumps({
                'action': decision.action,
                'target': decision.target,
                'trigger': trigger,
            })
            await db.create_inhibition(
                action=decision.action,
                pattern=pattern_json,
                reason=reason_seed,
                strength=p('output.inhibition.initial_strength'),
            )

    elif positive:
        existing = await db.find_matching_inhibition(decision.action, pattern_json)
        if existing:
            new_strength = max(existing['strength'] - p('output.inhibition.decay_amount'), 0.0)
            if new_strength < p('output.inhibition.delete_threshold'):
                await db.delete_inhibition(existing['id'])
            else:
                await db.update_inhibition(existing['id'], strength=new_strength)


# ── Habit tracking (Phase 4) ──


def _habit_delta(current_strength: float) -> float:
    """Piecewise strength increment: fast 0→0.4, medium 0.4→0.6, slow 0.6+."""
    if current_strength < 0.4:
        return p('output.habit.delta_fast')
    elif current_strength < 0.6:
        return p('output.habit.delta_medium')
    else:
        return p('output.habit.delta_slow')


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
        new_strength = min(p('output.habit.strength_cap'),
                           existing['strength'] + _habit_delta(existing['strength']))
        await db.update_habit(
            existing['id'],
            strength=new_strength,
            repetition_count=new_count,
            last_triggered=clock.now_utc(),
        )
    else:
        await db.create_habit(action, trigger_key, strength=0.1)


# ── Habit decay (TASK-036) ──

async def _decay_unfired_habits(fired_actions: set[str]) -> None:
    """Decay habits that did NOT fire this cycle based on time since last trigger.

    Only affects habits whose action was NOT among those just executed.
    Habits below delete threshold are pruned.
    """
    try:
        from datetime import datetime as _dt, timezone as _tz
        all_habits = await db.get_all_habits()
        now = clock.now_utc()

        for habit in all_habits:
            if habit['action'] in fired_actions:
                continue  # just fired — don't decay

            last_triggered = habit.get('last_triggered')
            if not last_triggered:
                continue

            # Parse last_triggered — may be ISO string or datetime
            if isinstance(last_triggered, str):
                lt = _dt.fromisoformat(last_triggered)
            else:
                lt = last_triggered
            if lt.tzinfo is None:
                lt = lt.replace(tzinfo=_tz.utc)

            elapsed_hours = (now - lt).total_seconds() / 3600.0
            new_strength = habit['strength'] - p('output.habit.decay_rate') * elapsed_hours

            if new_strength < p('output.habit.delete_threshold'):
                await db.delete_habit(habit['id'])
            else:
                await db.update_habit(habit['id'], strength=round(new_strength, 6))
    except Exception as e:
        print(f"  [HabitDecay] Error decaying habits: {e}")


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


# ── Epistemic Curiosity lifecycle (TASK-043) ──

async def _process_epistemic_curiosities(validated: ValidatedOutput,
                                          body_output: BodyOutput) -> None:
    """Handle EC birth, reinforcement, and eviction after cortex output.

    Birth: When cortex engaged with an epistemic gap score (read_content on
    a notification that had matching_threads), create or reinforce an EC.
    The question text comes from validated.internal_monologue (cortex output).

    Reinforcement: When content_consumed and gap_score matched an existing EC
    topic, boost intensity.

    Eviction: When at max_active and a new stronger question arrives, evict
    the weakest.
    """
    from models.state import EpistemicCuriosity, EPISTEMIC_CONFIG
    from models.event import Event

    try:
        # Check if cortex engaged with content (read_content action succeeded)
        content_reads = [
            ar for ar in body_output.executed
            if ar.action == 'read_content' and ar.success
        ]
        if not content_reads:
            return

        # Extract question from monologue if present
        monologue = validated.internal_monologue or ''
        question = _extract_epistemic_question(monologue)

        for read_result in content_reads:
            title = read_result.payload.get('title', '')
            content_id = read_result.payload.get('content_id', '') or ''

            if not title:
                continue

            # Template question if cortex didn't articulate one
            if not question:
                question = f"What more is there to know about {title}?"

            # Check existing ECs for merge
            active_ecs = await db.get_active_epistemic_curiosities(
                limit=EPISTEMIC_CONFIG['max_active'])

            merged = False
            for ec in active_ecs:
                # Simple keyword overlap check for merge (full embedding merge in TASK-044)
                if _topics_similar(ec.topic, title):
                    ec.intensity = min(1.0, ec.intensity + EPISTEMIC_CONFIG['reinforcement_boost'])
                    ec.last_reinforced_at = clock.now_utc().isoformat()
                    await db.upsert_epistemic_curiosity(ec)
                    merged = True
                    print(f"  [EC] Reinforced: {ec.topic} (intensity={ec.intensity:.2f})")
                    break

            if not merged:
                # Check if we need to evict
                if len(active_ecs) >= EPISTEMIC_CONFIG['max_active']:
                    evicted = await db.evict_weakest_curiosity()
                    if evicted:
                        # Create reflection seed for evicted EC
                        await db.append_event(Event(
                            event_type='self_reflection_seed',
                            source='self',
                            payload={
                                'ec_evicted': True,
                                'topic': evicted.topic,
                                'question': evicted.question,
                                'seed_text': f"I was wondering about {evicted.topic} but I've moved on.",
                            },
                        ))
                        print(f"  [EC] Evicted: {evicted.topic}")

                # Create new EC
                new_ec = EpistemicCuriosity(
                    topic=title,
                    question=question,
                    intensity=0.5,
                    source_type='notification',
                    source_id=content_id,
                )
                await db.upsert_epistemic_curiosity(new_ec)
                print(f"  [EC] Created: {title} — {question}")

    except Exception as e:
        print(f"  [EC] Error processing epistemic curiosities: {e}")


def _extract_epistemic_question(monologue: str) -> str:
    """Extract a question from the cortex's internal monologue.

    Looks for sentence-ending question marks. Returns the first question found,
    or empty string if none.
    """
    if not monologue:
        return ''

    sentences = re.split(r'[.!?]+', monologue)
    for s in sentences:
        s = s.strip()
        if '?' in monologue[monologue.find(s):monologue.find(s)+len(s)+1] if s else False:
            # This sentence was followed by a ? in the original
            return s.strip() + '?'

    # Simpler approach: find any question mark and take the preceding sentence
    if '?' in monologue:
        idx = monologue.index('?')
        # Walk back to find sentence start
        start = max(0, monologue.rfind('.', 0, idx) + 1,
                    monologue.rfind('!', 0, idx) + 1,
                    monologue.rfind('\n', 0, idx) + 1)
        return monologue[start:idx+1].strip()

    return ''


def _topics_similar(topic_a: str, topic_b: str) -> bool:
    """Simple keyword overlap check for topic merge.

    Returns True if >50% of significant words overlap.
    Full embedding-based merge is in TASK-044.
    """
    def keywords(t):
        words = t.lower().split()
        return {w.strip('.,!?;:"\'-()[]') for w in words if len(w) > 3}

    ka = keywords(topic_a)
    kb = keywords(topic_b)
    if not ka or not kb:
        return False

    overlap = len(ka & kb)
    min_size = min(len(ka), len(kb))
    return overlap / min_size > p('output.reflection.topic_similarity_threshold') if min_size > 0 else False


# ── Reflection processing (TASK-044) ──

async def process_reflection(validated: ValidatedOutput,
                             body_output: BodyOutput) -> dict:
    """Process post-read reflection outputs.

    After read_content, checks cortex output for reflection signals and
    produces appropriate effects: memories, EC resolution, mood changes,
    consumption tracking.

    Returns dict of effects applied for consumption tracking.
    """
    from models.state import EPISTEMIC_CONFIG

    effects = {
        'memory_created': False,
        'question_raised': False,
        'question_resolved': False,
        'thread_touched': False,
        'boring': False,
    }

    content_reads = [
        ar for ar in body_output.executed
        if ar.action == 'read_content' and ar.success
    ]
    if not content_reads:
        return effects

    monologue = validated.internal_monologue or ''
    # TASK-045: explicit reflection fields override boring detection —
    # if the cortex explicitly declared a reflection outcome, trust it
    has_explicit_reflection = any([
        validated.reflection_memory,
        validated.reflection_question,
        validated.resolves_question,
    ])
    is_boring = _is_boring_reflection(monologue) and not has_explicit_reflection

    for read_result in content_reads:
        content_id = read_result.payload.get('content_id', '')
        title = read_result.payload.get('title', '')

        # Track initial consumption in content_pool
        try:
            await db.update_pool_item(
                content_id,
                consumed=True,
                consumed_at=clock.now_utc(),
                consumption_output=json.dumps(effects),
            )
        except Exception as e:
            print(f"  [Reflection] Failed to track consumption: {e}")

        if is_boring:
            effects['boring'] = True
            # Boring: slight diversive drain
            try:
                drives = await db.get_drives_state()
                drives.diversive_curiosity = clamp(drives.diversive_curiosity + p('output.reflection.boring_curiosity_drain'))
                await db.save_drives_state(drives)
            except Exception as e:
                print(f"  [Reflection] Failed to update boring drives: {e}")
            continue

        # ── Detect reflection signals (TASK-045: explicit fields preferred) ──
        # Memory signal: explicit field or regex fallback
        if validated.reflection_memory:
            effects['memory_created'] = True
            try:
                await db.insert_text_fragment(
                    content=validated.reflection_memory[:500],
                    fragment_type='reflection',
                )
            except Exception:
                pass
        elif _has_memory_signal(monologue):
            effects['memory_created'] = True
            try:
                await db.insert_text_fragment(
                    content=monologue[:500],
                    fragment_type='reflection',
                )
            except Exception:
                pass

        # Question signal: explicit field or regex fallback
        if validated.reflection_question:
            effects['question_raised'] = True
        elif _extract_epistemic_question(monologue):
            effects['question_raised'] = True

        # Resolution signal: explicit field or regex fallback
        resolves = validated.resolves_question
        if resolves:
            # Explicit: cortex declared what was resolved — match by topic
            try:
                active_ecs = await db.get_active_epistemic_curiosities(limit=5)
                for ec in active_ecs:
                    if _topics_similar(ec.topic, resolves) or _topics_similar(ec.topic, title):
                        await db.resolve_epistemic_curiosity(ec.id, f'content:{content_id}')
                        effects['question_resolved'] = True
                        print(f"  [Reflection] Resolved EC (explicit): {ec.topic} → mood bump +{EPISTEMIC_CONFIG['resolution_mood_bump']}")
                        break
            except Exception as e:
                print(f"  [Reflection] EC resolution failed: {e}")
        elif _has_resolution_signal(monologue):
            try:
                active_ecs = await db.get_active_epistemic_curiosities(limit=5)
                for ec in active_ecs:
                    if _topics_similar(ec.topic, title):
                        await db.resolve_epistemic_curiosity(ec.id, f'content:{content_id}')
                        effects['question_resolved'] = True
                        print(f"  [Reflection] Resolved EC: {ec.topic} → mood bump +{EPISTEMIC_CONFIG['resolution_mood_bump']}")
                        break
            except Exception as e:
                print(f"  [Reflection] EC resolution failed: {e}")

        # ── Totem weight update (TASK-045) ──
        if validated.relevant_to_visitor:
            await _update_totem_for_visitor(validated.relevant_to_visitor, title)

        # ── Thread touch (TASK-045) ──
        if validated.relevant_to_thread:
            touched = await _touch_thread_from_reflection(
                validated.relevant_to_thread, title)
            if touched:
                effects['thread_touched'] = True

        # ── Single drive read-modify-save for all non-boring effects ──
        try:
            drives = await db.get_drives_state()
            if effects['question_resolved']:
                drives.mood_valence = clamp(
                    drives.mood_valence + EPISTEMIC_CONFIG['resolution_mood_bump'],
                    -1.0, 1.0)
                drives.diversive_curiosity = clamp(
                    drives.diversive_curiosity + p('output.reflection.resolved_curiosity_drain'))  # satisfied
            if effects['memory_created']:
                drives.mood_valence = clamp(drives.mood_valence + p('output.reflection.memory_valence_bump'), -1.0, 1.0)
            if effects['question_raised']:
                drives.mood_arousal = clamp(drives.mood_arousal + p('output.reflection.question_arousal_bump'))
            await db.save_drives_state(drives)
        except Exception as e:
            print(f"  [Reflection] Failed to update drives: {e}")

        # Update consumption tracking with actual effects
        try:
            await db.update_pool_item(
                content_id,
                consumption_output=json.dumps(effects),
            )
        except Exception:
            pass

    return effects


async def _update_totem_for_visitor(visitor_id: str, content_title: str) -> None:
    """TASK-045: Boost totem weight when content connects to a visitor.

    Finds totems for the visitor whose entity overlaps with the content title,
    and boosts weight. If no matching totem, creates one.
    """
    try:
        totems = await db.get_totems(visitor_id=visitor_id, limit=20)
        matched = False
        for totem in totems:
            if _topics_similar(totem.entity, content_title):
                new_weight = min(1.0, totem.weight + p('output.reflection.totem_weight_boost'))
                await db.update_totem(
                    entity=totem.entity,
                    visitor_id=visitor_id,
                    weight=new_weight,
                    last_referenced=clock.now_utc(),
                )
                print(f"  [Reflection] Totem weight boost: {totem.entity} → {new_weight:.2f} (visitor:{visitor_id})")
                matched = True
                break
        if not matched:
            # Create a new totem linking this content topic to the visitor
            await db.insert_totem(
                visitor_id=visitor_id,
                entity=content_title,
                weight=p('output.reflection.new_totem_weight'),
                context=f'Content reflection connected to visitor',
                category='content',
            )
            print(f"  [Reflection] New totem: {content_title} → visitor:{visitor_id}")
    except Exception as e:
        print(f"  [Reflection] Totem update failed: {e}")


async def _touch_thread_from_reflection(thread_id: str, content_title: str) -> bool:
    """TASK-045: Touch a thread when content connects to it.

    Updates thread last_activity and appends a note about the connection.
    Returns True if the thread was found and touched.
    """
    try:
        thread = await db.get_thread_by_id(thread_id)
        if thread:
            await db.touch_thread(
                thread_id=thread_id,
                reason=f'Content reflection: {content_title}',
                content=f'{thread.content or ""}\n[reflection] Connected to: {content_title}'.strip(),
            )
            print(f"  [Reflection] Thread touched: {thread.title} ← {content_title}")
            return True
        else:
            print(f"  [Reflection] Thread {thread_id} not found, skipping touch")
            return False
    except Exception as e:
        print(f"  [Reflection] Thread touch failed: {e}")
        return False


def _is_boring_reflection(monologue: str) -> bool:
    """Detect if reflection expresses disinterest/boredom."""
    if not monologue:
        return True  # no reflection at all = boring

    boring_patterns = [
        r"nothing (?:new|interesting|special|notable)",
        r"(?:already knew|nothing to add|didn't connect|doesn't connect)",
        r"(?:not much here|not (?:really )?interesting|doesn't move me)",
        r"(?:moved on|skimming|boring)",
    ]
    text_lower = monologue.lower()
    return any(re.search(pat, text_lower) for pat in boring_patterns)


def _has_memory_signal(monologue: str) -> bool:
    """Detect if monologue contains something worth remembering."""
    if not monologue or len(monologue) < 20:
        return False

    memory_patterns = [
        r"(?:remind|remember|worth (?:keeping|noting))",
        r"(?:connects? to|relates? to|like when)",
        r"(?:learned|discovered|realized|noticed)",
        r"(?:interesting|fascinating|surprising|unexpected)",
    ]
    text_lower = monologue.lower()
    return any(re.search(pat, text_lower) for pat in memory_patterns)


def _has_resolution_signal(monologue: str) -> bool:
    """Detect if monologue expresses that a question was answered."""
    if not monologue:
        return False

    resolution_patterns = [
        r"(?:answer|explains|that's (?:what|why|how))",
        r"(?:now i (?:understand|know|see))",
        r"(?:this (?:answers|resolves|clarifies))",
        r"(?:makes sense now|mystery solved|so that's)",
    ]
    text_lower = monologue.lower()
    return any(re.search(pat, text_lower) for pat in resolution_patterns)
