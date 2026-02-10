"""Hippocampus Consolidate — memory writes, totem creation, contradiction detection. No LLM."""

from datetime import datetime, timezone
from models.event import Event
import db


async def hippocampus_consolidate(update: dict, visitor_id: str = None):
    """Write validated memory updates to DB."""

    update_type = update.get('type')
    content = update.get('content', {})

    if update_type == 'visitor_impression':
        if visitor_id:
            kwargs = {}
            if content.get('summary'):
                kwargs['summary'] = content['summary']
            if content.get('emotional_imprint'):
                kwargs['emotional_imprint'] = content['emotional_imprint']
            if kwargs:
                await db.update_visitor(visitor_id, **kwargs)

    elif update_type == 'trait_observation':
        if visitor_id and content.get('trait_category') and content.get('trait_key'):
            # Check for contradiction before writing
            existing = await db.get_latest_trait(
                visitor_id=visitor_id,
                category=content['trait_category'],
                key=content['trait_key'],
            )

            await db.insert_trait(
                visitor_id=visitor_id,
                trait_category=content['trait_category'],
                trait_key=content['trait_key'],
                trait_value=content.get('trait_value', ''),
                confidence=content.get('confidence', 0.5),
                source_event_id=content.get('source_event_id', ''),
            )

            # Contradiction detection
            if existing and existing.trait_value != content.get('trait_value'):
                await db.append_event(Event(
                    event_type='internal_shift_candidate',
                    source='self',
                    payload={
                        'visitor_id': visitor_id,
                        'trait_key': content['trait_key'],
                        'old_value': existing.trait_value,
                        'new_value': content.get('trait_value'),
                    },
                ))

    elif update_type == 'totem_create':
        if content.get('entity'):
            await db.insert_totem(
                visitor_id=visitor_id,
                entity=content['entity'],
                weight=content.get('weight', 0.5),
                context=content.get('context', ''),
                category=content.get('category', 'general'),
            )

    elif update_type == 'totem_update':
        if content.get('entity'):
            await db.update_totem(
                entity=content['entity'],
                visitor_id=visitor_id,
                weight=content.get('weight'),
                last_referenced=datetime.now(timezone.utc),
            )

    elif update_type == 'journal_entry':
        if content.get('text'):
            await db.insert_journal(
                content=content['text'],
                mood=content.get('mood'),
                tags=content.get('tags', []),
            )

    elif update_type == 'self_discovery':
        if content.get('text'):
            await db.append_self_discovery(content['text'])

    elif update_type == 'collection_add':
        if content.get('title'):
            await db.insert_collection_item(content)
