"""Hippocampus Consolidate — memory writes, totem creation, contradiction detection. No LLM.

TASK-070: After each SQLite write, also writes to conscious memory (MD files).
SQLite writes are primary (never removed); MD writes are additive.
"""

import re
from datetime import datetime, timezone
import clock
from models.event import Event
import db


async def hippocampus_consolidate(update: dict, visitor_id: str = None):
    """Write validated memory updates to DB + MD files."""

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
            # MD write — visitor file
            await _md_append_visitor(visitor_id, summary, imprint)
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

            # MD write — trait as prose in visitor file
            trait_val = content.get('trait_value', '')
            if trait_val:
                await _md_append_visitor(
                    visitor_id,
                    f"I noticed: {content['trait_key']} — {trait_val}",
                    None,
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
            # MD write — totem as prose
            entity = content['entity']
            ctx = content.get('context', '')
            entry = f"Something new I associate with them: {entity}"
            if ctx:
                entry += f" — {ctx}"
            if visitor_id:
                await _md_append_visitor(visitor_id, entry, None)

    elif update_type == 'totem_update':
        if content.get('entity'):
            await db.update_totem(
                entity=content['entity'],
                visitor_id=visitor_id,
                weight=content.get('weight'),
                last_referenced=clock.now_utc(),
            )

    elif update_type == 'journal_entry':
        text = content.get('text') or content.get('content') or content.get('entry')
        if text:
            await db.insert_journal(
                content=text,
                mood=content.get('mood'),
                tags=content.get('tags', []),
            )
            # MD write — journal
            await _md_append_journal(text, content.get('mood'), content.get('tags', []))

    elif update_type == 'self_discovery':
        if content.get('text'):
            await db.append_self_discovery(content['text'])
            # MD write — self discovery as journal entry
            await _md_append_journal(content['text'], None, ['self_discovery'])

    elif update_type == 'collection_add':
        if content.get('title'):
            await db.insert_collection_item(content)
            # MD write — collection catalog
            feeling = content.get('her_feeling', '')
            entry = f"- **{content['title']}**"
            if feeling:
                entry += f" — {feeling}"
            await _md_append_collection(entry)

    elif update_type == 'thread_create':
        title = content.get('title', 'untitled thought')
        initial = content.get('initial_thought', '')

        # ── Thread dedup (HOTFIX-003) ──
        # Check for existing open thread with same or similar topic
        existing_thread = await _find_duplicate_thread(title)
        if existing_thread:
            # Merge into existing thread instead of creating duplicate
            if initial:
                await db.append_to_thread(existing_thread.id, initial)
                slug = _slugify(existing_thread.title)
                await _md_append_thread(slug, initial)
            print(f"  [Memory] Thread dedup: merged into existing '{existing_thread.title}'")
        else:
            await db.create_thread(
                thread_type=content.get('thread_type', 'question'),
                title=title,
                priority=content.get('priority', 0.5),
                content=initial,
                tags=content.get('tags', []),
                source_visitor_id=visitor_id,
            )
            # MD write — thread file
            slug = _slugify(title)
            if initial:
                await _md_append_thread(slug, initial)

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
            # MD write — thread update
            slug = _slugify(thread.title)
            update_text = (content.get('content')
                           or content.get('new_content')
                           or content.get('reason')
                           or content.get('touch_reason', ''))
            if update_text:
                await _md_append_thread(slug, update_text)
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
            # MD write — thread resolution
            slug = _slugify(thread.title)
            resolution = content.get('resolution', 'Resolved.')
            await _md_append_thread(slug, f"Resolved: {resolution}")
        else:
            print(f"  [Memory] Skipped thread_close — no unique thread match "
                  f"(id={content.get('thread_id')}, title={content.get('title')})")


# ── Thread dedup helpers (HOTFIX-003) ──

THREAD_DEDUP_SIMILARITY_THRESHOLD = 0.5  # Jaccard content-word overlap threshold


_STOP_WORDS = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
                'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                'would', 'could', 'should', 'may', 'might', 'can', 'shall',
                'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                'it', 'its', 'this', 'that', 'what', 'which', 'who', 'whom',
                'how', 'when', 'where', 'why', 'and', 'but', 'or', 'nor',
                'not', 'no', 'so', 'if', 'my', 'me', 'i', 'we', 'they',
                'he', 'she', 'you', 'about'}


def _normalize_words(text: str) -> set[str]:
    """Extract normalized content words from text, stripping punctuation and stop words."""
    words = text.lower().split()
    return {re.sub(r'[^\w-]', '', w) for w in words
            if re.sub(r'[^\w-]', '', w) and re.sub(r'[^\w-]', '', w) not in _STOP_WORDS}


async def _find_duplicate_thread(title: str):
    """Find an existing open thread with the same or similar topic.

    Returns the matching Thread if found, None otherwise.
    Uses exact case-insensitive match first, then fuzzy word overlap.
    """
    try:
        open_threads = await db.get_open_threads()
        title_lower = title.lower().strip()
        title_words = _normalize_words(title)

        for existing in open_threads:
            existing_lower = existing.title.lower().strip()

            # Exact match (after stripping)
            if existing_lower.rstrip('?!.') == title_lower.rstrip('?!.'):
                return existing

            # Fuzzy match — Jaccard word overlap
            existing_words = _normalize_words(existing.title)
            union = existing_words | title_words
            if not union:
                continue
            overlap = len(existing_words & title_words) / len(union)
            if overlap >= THREAD_DEDUP_SIMILARITY_THRESHOLD:
                return existing
    except Exception as e:
        print(f"  [Memory] Thread dedup check failed: {e}")

    return None


# ── MD write helpers ──
# Each wraps in try/except so SQLite writes succeed independently.

def _slugify(text: str, max_len: int = 50) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:max_len]


async def _md_append_visitor(visitor_id: str, summary: str = None,
                             imprint: str = None):
    """Append to visitor's MD file."""
    try:
        from memory_writer import get_memory_writer
        from memory_translator import scrub_numbers
        writer = get_memory_writer()
        parts = []
        if summary:
            parts.append(scrub_numbers(summary))
        if imprint:
            parts.append(f"Feeling: {scrub_numbers(imprint)}")
        if parts:
            # Try to get visitor name for the file header
            name = None
            try:
                visitor = await db.get_visitor(visitor_id)
                if visitor:
                    name = visitor.name
            except Exception:
                pass
            await writer.append_visitor(visitor_id, name or visitor_id,
                                        '\n'.join(parts))
    except Exception as e:
        print(f"  [Memory] MD visitor write failed: {e}")


async def _md_append_journal(text: str, mood: str = None,
                             tags: list[str] = None):
    """Append to today's journal MD file."""
    try:
        from memory_writer import get_memory_writer
        from memory_translator import scrub_numbers
        writer = get_memory_writer()
        await writer.append_journal(scrub_numbers(text), mood_desc=mood, tags=tags)
    except Exception as e:
        print(f"  [Memory] MD journal write failed: {e}")


async def _md_append_collection(entry: str):
    """Append to collection catalog MD."""
    try:
        from memory_writer import get_memory_writer
        from memory_translator import scrub_numbers
        writer = get_memory_writer()
        await writer.append_collection(scrub_numbers(entry))
    except Exception as e:
        print(f"  [Memory] MD collection write failed: {e}")


async def _md_append_thread(slug: str, text: str):
    """Append to thread MD file."""
    try:
        from memory_writer import get_memory_writer
        from memory_translator import scrub_numbers
        writer = get_memory_writer()
        await writer.append_thread(slug, scrub_numbers(text))
    except Exception as e:
        print(f"  [Memory] MD thread write failed: {e}")
