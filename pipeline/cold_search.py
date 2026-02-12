"""Cold memory search — semantic search over past conversations and monologues.

Used ONLY during sleep consolidation. Finds older memories that may connect
to today's salient moments, enabling cross-session insight formation.

All failures return empty list (non-blocking — sleep proceeds with hot context only).
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

import db
from db import JST
from pipeline.embed import embed


async def search_cold_memory(
    query: str,
    limit: int = 3,
    exclude_today: bool = True,
) -> list[dict]:
    """Search cold memory for entries semantically similar to query.

    Returns list of dicts matching sleep_reflect() expected format:
        [{'date': '2026-02-10', 'summary': '...', 'context': '...', 'source_type': '...'}]

    Args:
        query: The moment summary to search for related memories.
        limit: Maximum number of results.
        exclude_today: If True, exclude entries from the current JST day.
    """
    # 1. Embed the query
    query_vec = await embed(query)
    if query_vec is None:
        return []

    # 2. Compute exclusion boundary (start of today JST as UTC ISO)
    exclude_after_iso = None
    if exclude_today:
        exclude_after_iso = _jst_today_start_utc()

    # 3. Vector search
    try:
        raw_hits = await db.vector_search_cold_memory(
            query_embedding=query_vec,
            limit=limit,
            exclude_after_iso=exclude_after_iso,
        )
    except Exception as e:
        print(f"[ColdSearch] Vector search failed: {e}")
        return []

    if not raw_hits:
        return []

    # 4. Enrich each hit with surrounding context
    results = []
    for hit in raw_hits:
        try:
            context = await _fetch_cold_context(
                source_id=hit['source_id'],
                source_type=hit['source_type'],
            )
        except Exception as e:
            print(f"[ColdSearch] Context fetch failed for {hit['source_id']}: {e}")
            context = ''

        # Parse date from ts_iso for display
        date_str = _parse_date_from_iso(hit.get('ts_iso', ''))

        results.append({
            'date': date_str,
            'summary': hit.get('text_content', ''),
            'context': context,
            'source_type': hit.get('source_type', ''),
        })

    return results


async def _fetch_cold_context(source_id: str, source_type: str) -> str:
    """Fetch surrounding context for a cold memory hit.

    For conversations: returns ±2 surrounding messages.
    For monologues: returns the cycle's dialogue.
    """
    if source_type == 'conversation':
        messages = await db.get_conversation_context(
            message_id=source_id, before=2, after=2,
        )
        if not messages:
            return ''
        lines = []
        for msg in messages:
            role_label = 'Visitor' if msg['role'] == 'visitor' else 'Her'
            lines.append(f"{role_label}: {msg['text'][:100]}")
        return ' | '.join(lines)

    elif source_type == 'monologue':
        cycle = await db.get_cycle_by_id(source_id)
        if not cycle:
            return ''
        # Return dialogue if available, otherwise the monologue itself
        dialogue = cycle.get('dialogue', '')
        if dialogue:
            return dialogue[:200]
        monologue = cycle.get('internal_monologue', '')
        return monologue[:200]

    return ''


def _jst_today_start_utc() -> str:
    """Return start of today (JST) as UTC ISO string."""
    now_jst = datetime.now(JST)
    start_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_jst.astimezone(timezone.utc)
    return start_utc.isoformat()


def _parse_date_from_iso(ts_iso: str) -> str:
    """Extract date string from ISO timestamp. Returns '?' on failure."""
    if not ts_iso:
        return '?'
    try:
        dt = datetime.fromisoformat(ts_iso)
        # Convert to JST for display consistency
        dt_jst = dt.astimezone(JST)
        return dt_jst.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return '?'
