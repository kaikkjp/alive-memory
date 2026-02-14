"""Executor — emit events, update state, write text fragments. No LLM."""

import uuid
from datetime import datetime, timezone
import clock
from models.event import Event
from models.pipeline import ValidatedOutput, ExecutionResult, ActionRequest
from pipeline.hippocampus_write import hippocampus_consolidate
from pipeline.hypothalamus import apply_expression_relief
import db

# Diegetic farewell lines by reason
END_ENGAGEMENT_LINES = {
    'tired': "She turns away slightly. The conversation seems to be over.",
    'boundary': "She straightens up. Something shifted.",
    'natural': "A comfortable silence settles. She goes back to her work.",
}


async def execute(validated_output: ValidatedOutput, visitor_id: str = None,
                  cycle_id: str = None) -> ExecutionResult:
    """Execute approved actions. Emit events. Update state. Write text fragments."""

    result = ExecutionResult()

    # Emit dialogue
    dialogue = validated_output.dialogue
    if dialogue and dialogue != '...':
        event = Event(
            event_type='action_speak',
            source='self',
            payload={
                'text': dialogue,
                'language': validated_output.dialogue_language,
                'target': visitor_id,
            },
        )
        await db.append_event(event)
        result.events_emitted += 1

        # Immediate drive relief — she spoke, expression need drops
        await apply_expression_relief('action_speak')

        # Log to conversation
        if visitor_id:
            await db.append_conversation(visitor_id, 'shopkeeper', dialogue)

        # Write text fragment for window display
        frag_type = 'response' if visitor_id else 'thought'
        try:
            await db.insert_text_fragment(
                content=dialogue,
                fragment_type=frag_type,
                cycle_id=cycle_id,
                visitor_id=visitor_id,
            )
        except Exception as e:
            print(f"  [TextFragment] Failed to write dialogue fragment: {e}")

    # Write internal monologue as thought fragment (if no dialogue)
    monologue = validated_output.internal_monologue
    if monologue and not (dialogue and dialogue != '...'):
        try:
            await db.insert_text_fragment(
                content=monologue,
                fragment_type='thought',
                cycle_id=cycle_id,
            )
        except Exception as e:
            print(f"  [TextFragment] Failed to write thought fragment: {e}")

    # Emit body state
    body_event = Event(
        event_type='action_body',
        source='self',
        payload={
            'expression': validated_output.expression,
            'body_state': validated_output.body_state,
            'gaze': validated_output.gaze,
        },
    )
    await db.append_event(body_event)
    result.events_emitted += 1

    # Execute approved actions
    monologue = validated_output.internal_monologue
    for action in validated_output.approved_actions:
        await execute_action(action, visitor_id, monologue=monologue)
        result.actions_executed.append(action.type)

    # Process memory updates (isolate failures so one bad update doesn't kill the rest)
    for update in validated_output.memory_updates:
        try:
            # Convert to dict at hippocampus_write boundary (out of scope for typing)
            await hippocampus_consolidate(
                {'type': update.type, 'content': update.content},
                visitor_id,
            )
            result.memory_updates_processed += 1
        except Exception as e:
            result.memory_update_failures += 1
            print(f"  [Memory Error] Failed to consolidate {update.type}: {e}")
            # Persist failure as event so it survives cycle boundary for diagnosis/retry
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

    # Update pool item status based on cortex actions
    # (When consuming content, what she does determines the pool outcome)
    pool_id = validated_output.focus_pool_id
    if pool_id:
        has_collection = any(
            u.type == 'collection_add'
            for u in validated_output.memory_updates
        )
        has_reflection = any(
            u.type in ('journal_entry', 'totem_create', 'totem_update')
            for u in validated_output.memory_updates
        )
        now = clock.now_utc()
        outcome = None
        if has_collection:
            outcome = 'accepted'
            await db.update_pool_item(pool_id, status='accepted', engaged_at=now)
        elif has_reflection:
            outcome = 'reflected'
            await db.update_pool_item(pool_id, status='reflected', engaged_at=now)

        # Couple pool status with source event outcome (spec §3.4)
        # Event outcome uses spec vocabulary (engaged|ignored|expired);
        # pool-level detail (accepted|reflected) lives in content_pool.status.
        if outcome:
            result.pool_outcome = outcome
            pool_item = await db.get_pool_item_by_id(pool_id)
            if pool_item and pool_item.get('source_event_id'):
                await db.update_event_outcome(
                    pool_item['source_event_id'], 'engaged', engaged_at=now
                )

    # Update drives if resonance flagged
    if validated_output.resonance:
        drives = await db.get_drives_state()
        drives.social_hunger = max(0.0, drives.social_hunger - 0.15)
        drives.energy = min(1.0, drives.energy + 0.05)
        drives.mood_valence = min(1.0, drives.mood_valence + 0.1)
        await db.save_drives_state(drives)
        result.resonance_applied = True

    # Update engagement (skip if end_engagement is approved — she's leaving)
    ending = any(
        a.type == 'end_engagement'
        for a in validated_output.approved_actions
    )
    if visitor_id and dialogue and dialogue != '...' and not ending:
        await db.update_engagement_state(
            status='engaged',
            visitor_id=visitor_id,
            last_activity=clock.now_utc(),
        )
        # Increment turn count
        engagement = await db.get_engagement_state()
        await db.update_engagement_state(turn_count=engagement.turn_count + 1)

    return result


async def execute_action(action: ActionRequest, visitor_id: str, monologue: str = ''):
    """Execute a single approved action."""

    action_type = action.type
    detail = action.detail

    if action_type == 'accept_gift':
        item_id = str(uuid.uuid4())
        location = detail.get('location', 'counter')
        description = detail.get('description', detail.get('title', 'a gift'))
        await db.insert_collection_item({
            'id': item_id,
            'item_type': detail.get('item_type', 'link'),
            'title': detail.get('title', 'untitled gift'),
            'url': detail.get('url'),
            'description': description,
            'location': location,
            'origin': 'gift',
            'gifted_by': visitor_id,
            'her_feeling': detail.get('her_feeling'),
            'emotional_tags': detail.get('emotional_tags', []),
        })

        # Assign shelf slot + queue sprite generation for visible items
        if location in ('shelf', 'counter'):
            try:
                from pipeline.sprite_gen import queue_sprite_generation
                slot_id = await db.assign_shelf_slot(item_id, description)
                if slot_id:
                    # Generate item sprite filename
                    safe_desc = description[:30].replace(' ', '_').lower()
                    sprite_name = f'item_{item_id[:8]}_{safe_desc}.png'
                    await db.update_shelf_sprite(slot_id, sprite_name)
                    await queue_sprite_generation(sprite_name)
            except Exception as e:
                print(f"  [ShelfAssign] Failed: {e}")

    elif action_type == 'decline_gift':
        await db.append_event(Event(
            event_type='action_decline_gift',
            source='self',
            payload={'reason': detail.get('reason', ''), 'visitor_id': visitor_id},
        ))

    elif action_type == 'show_item':
        item_id = detail.get('item_id')
        await db.append_event(Event(
            event_type='action_show_item',
            source='self',
            payload={'item_id': item_id, 'target': visitor_id},
        ))

    elif action_type == 'write_journal':
        # Use detail text if provided; fall back to internal monologue
        # so journal entries aren't blank when LLM omits text in detail
        journal_text = detail.get('text', '') or monologue
        if journal_text:
            await db.insert_journal(
                content=journal_text,
                mood=detail.get('mood'),
                tags=detail.get('tags', []),
            )
            # Write journal text fragment for window display
            try:
                await db.insert_text_fragment(
                    content=journal_text,
                    fragment_type='journal',
                    visitor_id=visitor_id,
                )
            except Exception as e:
                print(f"  [TextFragment] Failed to write journal fragment: {e}")
        await apply_expression_relief('write_journal')

    elif action_type == 'post_x_draft':
        await db.append_event(Event(
            event_type='action_post_x',
            source='self',
            payload={'draft': detail.get('text', '')},
        ))
        await apply_expression_relief('post_x_draft')

    elif action_type == 'close_shop':
        await db.update_room_state(shop_status='closed')
        await db.append_event(Event(
            event_type='action_close_shop',
            source='self',
            payload={},
        ))

    elif action_type == 'end_engagement':
        reason = detail.get('reason', 'natural')

        # Emit farewell body event
        farewell_line = END_ENGAGEMENT_LINES.get(reason, END_ENGAGEMENT_LINES['natural'])
        await db.append_event(Event(
            event_type='action_end_engagement',
            source='self',
            payload={'reason': reason, 'farewell': farewell_line},
        ))

        # Transition to cooldown
        await db.update_engagement_state(
            status='cooldown',
            last_activity=clock.now_utc(),
        )

    elif action_type == 'place_item':
        # Put down whatever she's holding
        if visitor_id:
            await db.update_visitor(visitor_id, hands_state=None)
        await db.append_event(Event(
            event_type='action_room_delta',
            source='self',
            payload={'action': 'place_item', **detail},
        ))

    elif action_type == 'rearrange':
        await db.append_event(Event(
            event_type='action_room_delta',
            source='self',
            payload=detail,
        ))
        await apply_expression_relief('rearrange')
