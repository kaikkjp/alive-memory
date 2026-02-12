"""Hippocampus Consolidate — memory writes, totem creation, contradiction detection. No LLM."""

from datetime import datetime, timezone
from models.event import Event
import db


async def hippocampus_consolidate(update: dict, visitor_id: str = None):
    """Write validated memory updates to DB."""

    update_type = update.get('type')
    content = update.get('content', {})

    if update_type == 'visitor_impression':
        if not visitor_id:
            print(f"  [Memory] Skipped visitor_impression — no visitor_id")
            return
        kwargs = {}
        # Accept aliases: LLM may output 'impression' instead of 'summary',
        # or 'feeling' instead of 'emotional_imprint'
        summary = (content.get('summary')
                   or content.get('impression')
                   or content.get('description'))
        imprint = (content.get('emotional_imprint')
                   or content.get('feeling')
                   or content.get('emotion'))
        if summary:
            kwargs['summary'] = summary
        if imprint:
            kwargs['emotional_imprint'] = imprint
        if kwargs:
            await db.update_visitor(visitor_id, **kwargs)
        else:
            print(f"  [Memory] Skipped visitor_impression — no usable fields in: {list(content.keys())}")

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
        else:
            missing = []
            if not visitor_id:
                missing.append('visitor_id')
            if not content.get('trait_category'):
                missing.append('trait_category')
            if not content.get('trait_key'):
                missing.append('trait_key')
            print(f"  [Memory] Skipped trait_observation — missing: {missing}")

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
        text = content.get('text') or content.get('content') or content.get('entry')
        if text:
            await db.insert_journal(
                content=text,
                mood=content.get('mood'),
                tags=content.get('tags', []),
            )

    elif update_type == 'self_discovery':
        if content.get('text'):
            await db.append_self_discovery(content['text'])

    elif update_type == 'collection_add':
        if content.get('title'):
            await db.insert_collection_item(content)

    elif update_type == 'thread_create':
        title = content.get('title', 'untitled thought')
        await db.create_thread(
            thread_type=content.get('thread_type', 'question'),
            title=title,
            priority=content.get('priority', 0.5),
            content=content.get('initial_thought', ''),
            tags=content.get('tags', []),
            source_visitor_id=visitor_id,
        )

    elif update_type == 'thread_update':
        thread = None
        if content.get('thread_id'):
            thread = await db.get_thread_by_id(content['thread_id'])
        elif content.get('title'):
            thread = await db.get_thread_by_title(content['title'])
        if thread:
            await db.touch_thread(
                thread.id,
                reason=content.get('reason') if 'reason' in content else content.get('touch_reason', 'thought about it'),
                content=content.get('content') if 'content' in content else content.get('new_content'),
                status=content.get('status') if 'status' in content else content.get('new_status'),
            )
        else:
            print(f"  [Memory] Skipped thread_update — no unique thread match "
                  f"(id={content.get('thread_id')}, title={content.get('title')})")

    elif update_type == 'thread_close':
        thread = None
        if content.get('thread_id'):
            thread = await db.get_thread_by_id(content['thread_id'])
        elif content.get('title'):
            thread = await db.get_thread_by_title(content['title'])
        if thread:
            await db.touch_thread(
                thread.id,
                reason='resolved',
                content=content.get('resolution'),
                status='closed',
            )
        else:
            print(f"  [Memory] Skipped thread_close — no unique thread match "
                  f"(id={content.get('thread_id')}, title={content.get('title')})")
