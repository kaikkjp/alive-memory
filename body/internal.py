"""Internal action executors — extracted from pipeline/body.py.

These handle all pre-existing actions: gifts, journal, shop state,
content reading, self-modification, etc.  Behavior is identical to the
original if/elif chain; the only change is the dispatch mechanism.
"""

from __future__ import annotations

import uuid

import clock
from models.event import Event
from models.pipeline import ActionRequest, ActionResult
from pipeline.hypothalamus import apply_expression_relief
from body.executor import register
import db

# Diegetic farewell lines by reason
END_ENGAGEMENT_LINES = {
    'tired': "She turns away slightly. The conversation seems to be over.",
    'boundary': "She straightens up. Something shifted.",
    'natural': "A comfortable silence settles. She goes back to her work.",
}


@register('accept_gift')
async def execute_accept_gift(action: ActionRequest, visitor_id: str = None,
                              monologue: str = '') -> ActionResult:
    detail = action.detail
    result = ActionResult(action='accept_gift', timestamp=clock.now_utc())

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

    return result


@register('decline_gift')
async def execute_decline_gift(action: ActionRequest, visitor_id: str = None,
                               monologue: str = '') -> ActionResult:
    result = ActionResult(action='decline_gift', timestamp=clock.now_utc())
    await db.append_event(Event(
        event_type='action_decline_gift',
        source='self',
        payload={'reason': action.detail.get('reason', ''), 'visitor_id': visitor_id},
    ))
    result.side_effects.append('event_emitted')
    return result


@register('show_item')
async def execute_show_item(action: ActionRequest, visitor_id: str = None,
                            monologue: str = '') -> ActionResult:
    result = ActionResult(action='show_item', timestamp=clock.now_utc())
    item_id = action.detail.get('item_id')
    await db.append_event(Event(
        event_type='action_show_item',
        source='self',
        payload={'item_id': item_id, 'target': visitor_id},
    ))
    result.side_effects.append('event_emitted')
    return result


@register('write_journal')
async def execute_write_journal(action: ActionRequest, visitor_id: str = None,
                                monologue: str = '') -> ActionResult:
    detail = action.detail
    result = ActionResult(action='write_journal', timestamp=clock.now_utc())

    journal_text = (detail.get('text', '') or '').strip()
    if journal_text:
        await db.insert_journal(
            content=journal_text,
            mood=detail.get('mood'),
            tags=detail.get('tags', []),
        )
        result.content = journal_text
        result.side_effects.append('journal_entry_created')
        await db.append_event(Event(
            event_type='action_journal',
            source='self',
            payload={'content_length': len(journal_text)},
        ))
        try:
            await db.insert_text_fragment(
                content=journal_text,
                fragment_type='journal',
                visitor_id=visitor_id,
            )
        except Exception as e:
            print(f"  [TextFragment] Failed to write journal fragment: {e}")
        await apply_expression_relief('write_journal')
    else:
        # No distinct journal content — monologue already captured in cycle_log.
        # Half drive relief: she intended to write but had nothing new to say.
        await apply_expression_relief('write_journal_skipped')
        result.side_effects.append('journal_skipped_no_content')

    return result


@register('post_x_draft')
async def execute_post_x_draft(action: ActionRequest, visitor_id: str = None,
                               monologue: str = '') -> ActionResult:
    result = ActionResult(action='post_x_draft', timestamp=clock.now_utc())
    await db.append_event(Event(
        event_type='action_post_x',
        source='self',
        payload={'draft': action.detail.get('text', '')},
    ))
    await apply_expression_relief('post_x_draft')
    result.side_effects.append('event_emitted')
    return result


@register('close_shop')
async def execute_close_shop(action: ActionRequest, visitor_id: str = None,
                             monologue: str = '') -> ActionResult:
    result = ActionResult(action='close_shop', timestamp=clock.now_utc())
    await db.update_room_state(shop_status='closed')
    await db.append_event(Event(
        event_type='action_close_shop',
        source='self',
        payload={},
    ))
    result.side_effects.append('room_state_updated')
    return result


@register('open_shop')
async def execute_open_shop(action: ActionRequest, visitor_id: str = None,
                            monologue: str = '') -> ActionResult:
    result = ActionResult(action='open_shop', timestamp=clock.now_utc())
    await db.update_room_state(shop_status='open')
    await db.append_event(Event(
        event_type='action_open_shop',
        source='self',
        payload={},
    ))
    result.side_effects.append('room_state_updated')
    return result


@register('end_engagement')
async def execute_end_engagement(action: ActionRequest, visitor_id: str = None,
                                 monologue: str = '') -> ActionResult:
    result = ActionResult(action='end_engagement', timestamp=clock.now_utc())
    reason = action.detail.get('reason', 'natural')
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
    return result


@register('place_item')
async def execute_place_item(action: ActionRequest, visitor_id: str = None,
                             monologue: str = '') -> ActionResult:
    result = ActionResult(action='place_item', timestamp=clock.now_utc())
    if visitor_id:
        await db.update_visitor(visitor_id, hands_state=None)
    await db.append_event(Event(
        event_type='action_room_delta',
        source='self',
        payload={'action': 'place_item', **action.detail},
    ))
    result.side_effects.append('room_delta_emitted')
    return result


@register('rearrange')
async def execute_rearrange(action: ActionRequest, visitor_id: str = None,
                            monologue: str = '') -> ActionResult:
    result = ActionResult(action='rearrange', timestamp=clock.now_utc())
    await db.append_event(Event(
        event_type='action_room_delta',
        source='self',
        payload=action.detail,
    ))
    await apply_expression_relief('rearrange')
    result.side_effects.append('room_delta_emitted')
    return result


@register('read_content')
async def execute_read_content(action: ActionRequest, visitor_id: str = None,
                               monologue: str = '') -> ActionResult:
    detail = action.detail
    result = ActionResult(action='read_content', timestamp=clock.now_utc())

    content_id = detail.get('content_id')
    if not content_id:
        result.success = False
        result.error = 'no content_id in detail'
        return result

    pool_item = await db.get_pool_item_by_id(content_id)
    if not pool_item:
        result.success = False
        result.error = f'content_id {content_id} not found in pool'
        return result

    # Use cached enriched_text if available, otherwise use raw content
    full_text = pool_item.get('enriched_text') or pool_item.get('content') or ''
    # Truncate to ~1500 tokens (~6000 chars)
    if len(full_text) > 6000:
        full_text = full_text[:6000] + '\n[...truncated]'
    result.content = full_text
    result.payload = {
        'content_id': content_id,
        'full_content': full_text,
        'title': pool_item.get('title', ''),
        'content_type': pool_item.get('content_type', ''),
        'source': pool_item.get('source_channel', ''),
    }
    # Mark as engaged in content pool
    await db.update_pool_item(
        content_id,
        status='engaged',
        engaged_at=clock.now_utc(),
    )
    result.side_effects.append('content_read')
    await db.append_event(Event(
        event_type='content_consumed',
        source='self',
        payload={
            'content_id': content_id,
            'title': pool_item.get('title', ''),
        },
    ))
    return result


@register('save_for_later')
async def execute_save_for_later(action: ActionRequest, visitor_id: str = None,
                                 monologue: str = '') -> ActionResult:
    result = ActionResult(action='save_for_later', timestamp=clock.now_utc())
    content_id = action.detail.get('content_id')
    if content_id:
        await db.save_content_for_later(content_id)
        result.side_effects.append('content_saved')
    else:
        result.success = False
        result.error = 'no content_id in detail'
    return result


@register('mention_in_conversation')
async def execute_mention_in_conversation(action: ActionRequest, visitor_id: str = None,
                                          monologue: str = '') -> ActionResult:
    detail = action.detail
    result = ActionResult(action='mention_in_conversation', timestamp=clock.now_utc())

    content_id = detail.get('content_id')
    if not content_id:
        result.success = False
        result.error = 'no content_id in detail'
        return result

    pool_item = await db.get_pool_item_by_id(content_id)
    if not pool_item:
        result.success = False
        result.error = f'content_id {content_id} not found in pool'
        return result

    result.payload = {
        'content_id': content_id,
        'title': pool_item.get('title', ''),
        'source': pool_item.get('source_channel', ''),
        'content_type': pool_item.get('content_type', ''),
    }
    result.side_effects.append('content_mentioned')
    await db.update_pool_item(content_id, status='seen',
                              seen_at=clock.now_utc())
    return result


@register('modify_self')
async def execute_modify_self(action: ActionRequest, visitor_id: str = None,
                              monologue: str = '') -> ActionResult:
    result = ActionResult(action='modify_self', timestamp=clock.now_utc())
    detail = action.detail

    from db.parameters import set_param, get_param
    param_key = detail.get('parameter', '')
    new_value = detail.get('value')
    reason = detail.get('reason', 'self-modification')
    try:
        old = await get_param(param_key)
        if old is None:
            result.success = False
            result.error = f'Unknown parameter: {param_key}'
        else:
            await set_param(param_key, float(new_value),
                           modified_by='self', reason=reason)
            result.success = True
            result.payload = {
                'parameter': param_key,
                'old_value': old['value'],
                'new_value': float(new_value),
                'reason': reason,
            }
            await db.append_event(Event(
                event_type='action_modify_self',
                source='self',
                payload=result.payload,
            ))
    except ValueError as e:
        result.success = False
        result.error = str(e)  # bounds violation message from set_param

    return result
