"""Output processing — post-action feedback loop.

Position: after Body.
Question it answers: "What changed in the world because of what she did?"

Handles: memory consolidation, pool status updates, drive adjustments,
engagement state updates, action logging, suppression reflection seeds.

Phase 2: Full implementation with action logging, drive adjustments from
outcomes, and self-reflection seed injection for suppressed high-impulse
actions.
Phase 3 will add: inhibition formation, metacognitive monitoring.
Phase 4 will add: habit pattern tracking.
"""

import clock
from models.event import Event
from models.pipeline import (
    ValidatedOutput, MotorPlan, BodyOutput, CycleOutput,
)
from pipeline.action_registry import ACTION_REGISTRY
from pipeline.hippocampus_write import hippocampus_consolidate
import db


async def process_output(body_output: BodyOutput, validated: ValidatedOutput,
                         visitor_id: str = None, motor_plan: MotorPlan = None,
                         cycle_id: str = None) -> CycleOutput:
    """Process post-action side effects.

    Memory consolidation, pool updates, drive adjustments, engagement state,
    action logging, and suppression reflection seeds.
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

    # ── Update drives if resonance flagged ──
    if validated.resonance:
        drives = await db.get_drives_state()
        drives.social_hunger = max(0.0, drives.social_hunger - 0.15)
        drives.energy = min(1.0, drives.energy + 0.05)
        drives.mood_valence = min(1.0, drives.mood_valence + 0.1)
        await db.save_drives_state(drives)
        result.resonance_applied = True

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
        else:
            # Continuing conversation — update activity and increment turn
            await db.update_engagement_state(
                last_activity=now,
                turn_count=engagement.turn_count + 1,
            )

    # ── Drive adjustments from action outcomes (Phase 2) ──
    if body_output.executed:
        drives = await db.get_drives_state()
        failures = [r for r in body_output.executed if not r.success]
        successes = [r for r in body_output.executed if r.success]
        changed = False
        if failures:
            drives.mood_valence = max(-1.0, drives.mood_valence - 0.05 * len(failures))
            changed = True
        if successes:
            drives.mood_valence = min(1.0, drives.mood_valence + 0.02 * len(successes))
            changed = True
        if changed:
            await db.save_drives_state(drives)

    # ── Log actions to action_log (Phase 2) ──
    if motor_plan and cycle_id:
        await _log_motor_plan(motor_plan, body_output, cycle_id)

    # ── Suppression reflection seed (Phase 2) ──
    if motor_plan:
        await _inject_reflection_seed(motor_plan)

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
