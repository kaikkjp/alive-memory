"""Output processing — post-action feedback loop.

Position: after Body.
Question it answers: "What changed in the world because of what she did?"

Handles: memory consolidation, pool status updates, drive adjustments,
engagement state updates.

Phase 1: Stub that replicates executor post-action behavior exactly.
Phase 2 will add: suppressed-action reflection seeds, drive adjustments from outcomes.
Phase 3 will add: inhibition formation, metacognitive monitoring.
Phase 4 will add: habit pattern tracking.
"""

import clock
from models.event import Event
from models.pipeline import (
    ValidatedOutput, BodyOutput, CycleOutput,
)
from pipeline.hippocampus_write import hippocampus_consolidate
import db


async def process_output(body_output: BodyOutput, validated: ValidatedOutput,
                         visitor_id: str = None) -> CycleOutput:
    """Process post-action side effects.

    Memory consolidation, pool updates, drive adjustments, engagement state.
    All within the caller's transaction boundary.
    """
    result = CycleOutput(body_output=body_output)

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
    dialogue = validated.dialogue
    ending = any(
        a.type == 'end_engagement'
        for a in validated.approved_actions
    )
    if visitor_id and dialogue and dialogue != '...' and not ending:
        await db.update_engagement_state(
            status='engaged',
            visitor_id=visitor_id,
            last_activity=clock.now_utc(),
        )
        engagement = await db.get_engagement_state()
        await db.update_engagement_state(turn_count=engagement.turn_count + 1)

    return result
