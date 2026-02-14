"""Body — execute approved actions, emit events, write text fragments.

Position: after Basal Ganglia.
Question it answers: "Can I physically do this, and what happened when I tried?"

The Body is thin. It receives approved actions from the MotorPlan and executes them.
It does NOT decide. It does NOT inhibit. It does NOT prioritize.
All of that already happened in the brain (Basal Ganglia).

Dialogue/monologue/body_state event emissions are body actions — they live here
permanently. Memory consolidation, pool updates, drive adjustments, and engagement
state updates live in output.py.
"""

import uuid

import clock
from models.event import Event
from models.pipeline import (
    ValidatedOutput, ActionRequest, MotorPlan,
    ActionResult, BodyOutput,
)
from pipeline.hypothalamus import apply_expression_relief
import db

# Diegetic farewell lines by reason
END_ENGAGEMENT_LINES = {
    'tired': "She turns away slightly. The conversation seems to be over.",
    'boundary': "She straightens up. Something shifted.",
    'natural': "A comfortable silence settles. She goes back to her work.",
}


async def execute_body(motor_plan: MotorPlan, validated: ValidatedOutput,
                       visitor_id: str = None, cycle_id: str = None) -> BodyOutput:
    """Execute approved actions from the motor plan. Emit events. Write text fragments.

    This is the body's work: dialogue emission, body state broadcast, and
    individual action execution. Post-action side effects (memory, drives,
    engagement) are handled by output.py.
    """
    output = BodyOutput()

    # ── Emit dialogue ──
    dialogue = validated.dialogue
    if dialogue and dialogue != '...':
        event = Event(
            event_type='action_speak',
            source='self',
            payload={
                'text': dialogue,
                'language': validated.dialogue_language,
                'target': visitor_id,
            },
        )
        await db.append_event(event)
        output.events_emitted += 1

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
    monologue = validated.internal_monologue
    if monologue and not (dialogue and dialogue != '...'):
        try:
            await db.insert_text_fragment(
                content=monologue,
                fragment_type='thought',
                cycle_id=cycle_id,
            )
        except Exception as e:
            print(f"  [TextFragment] Failed to write thought fragment: {e}")

    # ── Emit body state ──
    body_event = Event(
        event_type='action_body',
        source='self',
        payload={
            'expression': validated.expression,
            'body_state': validated.body_state,
            'gaze': validated.gaze,
        },
    )
    await db.append_event(body_event)
    output.events_emitted += 1

    # ── Execute approved actions from motor plan ──
    for decision in motor_plan.actions:
        # Use detail dict carried on ActionDecision (set by basal_ganglia)
        action_req = ActionRequest(type=decision.action, detail=decision.detail)
        result = await _execute_single_action(action_req, visitor_id, monologue=monologue)
        output.executed.append(result)

    return output


async def _execute_single_action(action: ActionRequest, visitor_id: str,
                                 monologue: str = '') -> ActionResult:
    """Execute a single approved action. Returns ActionResult."""

    action_type = action.type
    detail = action.detail
    result = ActionResult(action=action_type, timestamp=clock.now_utc())

    try:
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
            result.side_effects.append('collection_item_created')

            # Assign shelf slot + queue sprite generation for visible items
            if location in ('shelf', 'counter'):
                try:
                    from pipeline.sprite_gen import queue_sprite_generation
                    slot_id = await db.assign_shelf_slot(item_id, description)
                    if slot_id:
                        safe_desc = description[:30].replace(' ', '_').lower()
                        sprite_name = f'item_{item_id[:8]}_{safe_desc}.png'
                        await db.update_shelf_sprite(slot_id, sprite_name)
                        await queue_sprite_generation(sprite_name)
                        result.side_effects.append('shelf_slot_assigned')
                except Exception as e:
                    print(f"  [ShelfAssign] Failed: {e}")

        elif action_type == 'decline_gift':
            await db.append_event(Event(
                event_type='action_decline_gift',
                source='self',
                payload={'reason': detail.get('reason', ''), 'visitor_id': visitor_id},
            ))
            result.side_effects.append('event_emitted')

        elif action_type == 'show_item':
            item_id = detail.get('item_id')
            await db.append_event(Event(
                event_type='action_show_item',
                source='self',
                payload={'item_id': item_id, 'target': visitor_id},
            ))
            result.side_effects.append('event_emitted')

        elif action_type == 'write_journal':
            journal_text = detail.get('text', '') or monologue
            if journal_text:
                await db.insert_journal(
                    content=journal_text,
                    mood=detail.get('mood'),
                    tags=detail.get('tags', []),
                )
                result.content = journal_text
                result.side_effects.append('journal_entry_created')
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
            result.side_effects.append('event_emitted')

        elif action_type == 'close_shop':
            await db.update_room_state(shop_status='closed')
            await db.append_event(Event(
                event_type='action_close_shop',
                source='self',
                payload={},
            ))
            result.side_effects.append('room_state_updated')

        elif action_type == 'end_engagement':
            reason = detail.get('reason', 'natural')
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
            result.side_effects.append('engagement_ended')

        elif action_type == 'place_item':
            if visitor_id:
                await db.update_visitor(visitor_id, hands_state=None)
            await db.append_event(Event(
                event_type='action_room_delta',
                source='self',
                payload={'action': 'place_item', **detail},
            ))
            result.side_effects.append('room_delta_emitted')

        elif action_type == 'rearrange':
            await db.append_event(Event(
                event_type='action_room_delta',
                source='self',
                payload=detail,
            ))
            await apply_expression_relief('rearrange')
            result.side_effects.append('room_delta_emitted')

    except Exception as e:
        result.success = False
        result.error = f"{type(e).__name__}: {e}"
        print(f"  [Body] Action {action_type} failed: {e}")

    return result
