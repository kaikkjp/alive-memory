"""Executor — emit events, update state, write text fragments. No LLM."""

import uuid
from datetime import datetime, timezone
import clock
from models.event import Event
from pipeline.hippocampus_write import hippocampus_consolidate
from pipeline.hypothalamus import apply_expression_relief
import db

# Diegetic farewell lines by reason
END_ENGAGEMENT_LINES = {
    'tired': "She turns away slightly. The conversation seems to be over.",
    'boundary': "She straightens up. Something shifted.",
    'natural': "A comfortable silence settles. She goes back to her work.",
}


async def execute(validated_output: dict, visitor_id: str = None,
                  cycle_id: str = None):
    """Execute approved actions. Emit events. Update state. Write text fragments."""

    # Emit dialogue
    dialogue = validated_output.get('dialogue')
    if dialogue and dialogue != '...':
        event = Event(
            event_type='action_speak',
            source='self',
            payload={
                'text': dialogue,
                'language': validated_output.get('dialogue_language', 'en'),
                'target': visitor_id,
            },
        )
        await db.append_event(event)

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
    monologue = validated_output.get('internal_monologue', '')
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
            'expression': validated_output.get('expression', 'neutral'),
            'body_state': validated_output.get('body_state', 'sitting'),
            'gaze': validated_output.get('gaze', 'at_visitor'),
        },
    )
    await db.append_event(body_event)

    # Execute approved actions
    monologue = validated_output.get('internal_monologue', '')
    for action in validated_output.get('_approved_actions', []):
        await execute_action(action, visitor_id, monologue=monologue)

    # Process memory updates (isolate failures so one bad update doesn't kill the rest)
    for update in validated_output.get('memory_updates', []):
        try:
            await hippocampus_consolidate(update, visitor_id)
        except Exception as e:
            update_type = update.get('type', '?')
            print(f"  [Memory Error] Failed to consolidate {update_type}: {e}")
            # Persist failure as event so it survives cycle boundary for diagnosis/retry
            await db.append_event(Event(
                event_type='memory_consolidation_failed',
                source='self',
                payload={
                    'update_type': update_type,
                    'error': f"{type(e).__name__}: {e}",
                    'original_update': update,
                    'visitor_id': visitor_id,
                },
            ))

    # Update pool item status based on cortex actions
    # (When consuming content, what she does determines the pool outcome)
    pool_id = None
    if validated_output.get('_focus_pool_id'):
        pool_id = validated_output['_focus_pool_id']
    if pool_id:
        has_collection = any(
            u.get('type') == 'collection_add'
            for u in validated_output.get('memory_updates', [])
        )
        has_reflection = any(
            u.get('type') in ('journal_entry', 'totem_create', 'totem_update')
            for u in validated_output.get('memory_updates', [])
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
            pool_item = await db.get_pool_item_by_id(pool_id)
            if pool_item and pool_item.get('source_event_id'):
                await db.update_event_outcome(
                    pool_item['source_event_id'], 'engaged', engaged_at=now
                )

    # Update drives if resonance flagged
    if validated_output.get('resonance'):
        drives = await db.get_drives_state()
        drives.social_hunger = max(0.0, drives.social_hunger - 0.15)
        drives.energy = min(1.0, drives.energy + 0.05)
        drives.mood_valence = min(1.0, drives.mood_valence + 0.1)
        await db.save_drives_state(drives)

    # Update engagement (skip if end_engagement is approved — she's leaving)
    ending = any(
        a.get('type') == 'end_engagement'
        for a in validated_output.get('_approved_actions', [])
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


async def execute_action(action: dict, visitor_id: str, monologue: str = ''):
    """Execute a single approved action."""

    action_type = action.get('type')
    detail = action.get('detail', {})

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
