"""Hippocampus Recall — DB reads, compressed chunks. No LLM."""

from datetime import datetime, timezone
from db import JST
import clock
import db

MAX_CHUNK_TOKENS = 200  # approximate, measured by word count / 0.75


async def recall(requests: list[dict]) -> list[dict]:
    """Fetch compressed memory chunks. No LLM. DB only."""

    chunks = []

    for req in requests:
        if req['type'] == 'visitor_summary':
            visitor = await db.get_visitor(req['visitor_id'])
            if visitor:
                chunk = {
                    'label': f"Memory of {visitor.name or 'this visitor'}",
                    'content': compress_visitor(visitor),
                }
                chunks.append(chunk)

        elif req['type'] == 'visitor_totems':
            totems = await db.get_totems(
                visitor_id=req['visitor_id'],
                min_weight=req.get('min_weight', 0.3),
                limit=req.get('max_items', 5),
            )
            if totems:
                chunk = {
                    'label': 'Things I associate with them',
                    'content': format_totems(totems),
                }
                chunks.append(chunk)

        elif req['type'] == 'taste_knowledge':
            domain = req.get('domain', 'general')
            taste = await db.get_taste_knowledge(domain)
            if taste:
                chunks.append({
                    'label': f'My taste in {domain}',
                    'content': truncate(taste, MAX_CHUNK_TOKENS),
                })

        elif req['type'] == 'related_collection':
            items = await db.search_collection(
                query=req.get('query', ''),
                limit=req.get('max_items', 3),
            )
            if items:
                chunks.append({
                    'label': 'Related items in my collection',
                    'content': format_collection_items(items),
                })

        elif req['type'] == 'self_knowledge':
            knowledge = await db.get_self_discoveries()
            if knowledge:
                chunks.append({
                    'label': 'Things I know about myself',
                    'content': truncate(knowledge, MAX_CHUNK_TOKENS),
                })

        elif req['type'] == 'recent_journal':
            entries = await db.get_recent_journal(limit=req.get('max_items', 2))
            if entries:
                chunks.append({
                    'label': 'Recent thoughts',
                    'content': format_journal_entries(entries),
                })

        elif req['type'] == 'day_context':
            moments = await db.get_day_memory(
                visitor_id=req.get('visitor_id'),
                limit=req.get('max_items', 3),
                min_salience=req.get('min_salience', 0.3),
            )
            if moments:
                chunks.append({
                    'label': 'Earlier today',
                    'content': format_day_moments(moments),
                })

    return chunks


def compress_visitor(visitor) -> str:
    """Compress visitor data to ~150 tokens."""
    parts = []
    if visitor.name:
        parts.append(f"Name: {visitor.name}")
    parts.append(f"Visits: {visitor.visit_count}")
    parts.append(f"Trust: {visitor.trust_level}")
    if visitor.emotional_imprint:
        parts.append(f"I feel: {visitor.emotional_imprint}")
    if visitor.summary:
        parts.append(visitor.summary[:300])
    return "\n".join(parts)


def format_totems(totems: list) -> str:
    """Format totems with weight context."""
    lines = []
    for t in totems:
        weight_word = "deeply important" if t.weight > 0.8 else "notable" if t.weight > 0.5 else "passing"
        lines.append(f"- {t.entity} ({weight_word}): {t.context or 'no context'}")
    return "\n".join(lines)


def format_collection_items(items: list) -> str:
    """Format collection items for memory context."""
    lines = []
    for item in items:
        line = f"- {item.title}"
        if item.her_feeling:
            line += f" — {item.her_feeling[:100]}"
        lines.append(line)
    return "\n".join(lines)


def format_journal_entries(entries: list) -> str:
    """Format journal entries for memory context."""
    lines = []
    for entry in entries:
        content = entry.content[:200]
        if entry.mood:
            lines.append(f"[{entry.mood}] {content}")
        else:
            lines.append(content)
    return "\n".join(lines)


def truncate(text: str, max_tokens: int) -> str:
    """Approximate token truncation (words * 0.75 ≈ tokens)."""
    words = text.split()
    max_words = int(max_tokens * 0.75)
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def format_day_moments(moments: list) -> str:
    """Format day memory entries with relative time labels."""
    lines = []
    for m in moments:
        time_label = relative_time(m.ts)
        lines.append(f"[{time_label}] {m.summary}")
    return "\n".join(lines)


def relative_time(ts: datetime) -> str:
    """Convert timestamp to relative time label."""
    now = clock.now_utc()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    minutes = delta.total_seconds() / 60

    if minutes < 5:
        return "just now"
    elif minutes < 30:
        return "a little while ago"
    elif minutes < 90:
        return "about an hour ago"
    elif minutes < 240:
        hours = int(minutes / 60)
        return f"about {hours} hours ago"
    else:
        # Use JST for time-of-day labeling
        ts_jst = ts.astimezone(JST)
        hour = ts_jst.hour
        if hour < 12:
            return "this morning"
        elif hour < 17:
            return "this afternoon"
        else:
            return "this evening"
