"""db.memory — Visitors, traits, totems, collection, journal, day memory,
cold search, text fragments, shelf, chat tokens, visitor presence."""

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import clock
from models.event import Event
from models.state import (
    Visitor, VisitorTrait, Totem, CollectionItem, JournalEntry, DailySummary,
)
import db.connection as _connection
from db.connection import _write_lock, transaction, JST, COLD_SEARCH_ENABLED
from runtime_context import get_cycle_context, hash_text, resolve_cycle_id


def _estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _infer_memory_source() -> str:
    return 'awake' if get_cycle_context() else 'sleep'


async def _log_memory_write_event(
    memory_type: str,
    content_text: str,
    location: str,
    source: str | None = None,
    cycle_id: str | None = None,
    sleep_session_id: str | None = None,
    fact_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """Best-effort structured memory-write logging."""
    try:
        from db.analytics import log_memory_write

        text = content_text or ''
        await log_memory_write(
            memory_type=memory_type,
            source=source or _infer_memory_source(),
            content_hash=hash_text(text),
            tokens_written=_estimate_tokens(text),
            size_bytes=len(text.encode('utf-8')),
            cycle_id=resolve_cycle_id(cycle_id),
            sleep_session_id=sleep_session_id,
            fact_id=fact_id,
            location=location,
            payload=payload or {},
        )
    except Exception:
        # Memory-write evidence is best-effort and must not break runtime behavior.
        return


# ─── Visitors ───

async def get_visitor(visitor_id: str) -> Optional[Visitor]:
    db = await _connection.get_db()
    cursor = await db.execute("SELECT * FROM visitors WHERE id = ?", (visitor_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    return Visitor(
        id=row['id'], name=row['name'], trust_level=row['trust_level'],
        visit_count=row['visit_count'],
        first_visit=datetime.fromisoformat(row['first_visit']) if row['first_visit'] else None,
        last_visit=datetime.fromisoformat(row['last_visit']) if row['last_visit'] else None,
        summary=row['summary'], emotional_imprint=row['emotional_imprint'],
        hands_state=row['hands_state'],
    )


async def create_visitor(visitor_id: str) -> Visitor:
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        "INSERT OR IGNORE INTO visitors (id, visit_count, first_visit, last_visit) VALUES (?, 1, ?, ?)",
        (visitor_id, now, now)
    )
    return await get_visitor(visitor_id)


async def update_visitor(visitor_id: str, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [visitor_id]
    await _connection._exec_write(f"UPDATE visitors SET {sets} WHERE id = ?", tuple(vals))


async def increment_visit(visitor_id: str):
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        "UPDATE visitors SET visit_count = visit_count + 1, last_visit = ? WHERE id = ?",
        (now, visitor_id)
    )
    # Update trust level based on visit count
    visitor = await get_visitor(visitor_id)
    if visitor:
        new_trust = visitor.trust_level
        if visitor.visit_count >= 10:
            new_trust = 'familiar'
        elif visitor.visit_count >= 5:
            new_trust = 'regular'
        elif visitor.visit_count >= 2:
            new_trust = 'returner'
        if new_trust != visitor.trust_level:
            await update_visitor(visitor_id, trust_level=new_trust)


# ─── Visitor Traits ───

async def get_latest_trait(visitor_id: str, category: str, key: str) -> Optional[VisitorTrait]:
    db = await _connection.get_db()
    cursor = await db.execute(
        """SELECT * FROM visitor_traits
           WHERE visitor_id = ? AND trait_category = ? AND trait_key = ? AND status = 'active'
           ORDER BY observed_at DESC LIMIT 1""",
        (visitor_id, category, key)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_trait(row)


async def insert_trait(visitor_id: str, trait_category: str, trait_key: str,
                       trait_value: str, confidence: float = 0.5,
                       source_event_id: str = ''):
    trait_id = str(uuid.uuid4())
    observed_at = clock.now_utc().isoformat()
    await _connection._exec_write(
        """INSERT INTO visitor_traits
           (id, visitor_id, trait_category, trait_key, trait_value, observed_at, source_event_id, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (trait_id, visitor_id, trait_category, trait_key, trait_value,
         observed_at, source_event_id, confidence)
    )
    await _log_memory_write_event(
        memory_type='semantic',
        content_text=f"{trait_key}: {trait_value}",
        location='visitor_traits',
        fact_id=trait_id,
        payload={
            'visitor_id': visitor_id,
            'trait_category': trait_category,
            'trait_key': trait_key,
            'source_event_id': source_event_id,
            'observed_at': observed_at,
        },
    )
    try:
        from db.analytics import log_recall_injection

        await log_recall_injection(
            fact_id=trait_id,
            content_hash=hash_text(trait_value),
            injection_channel='event' if source_event_id else 'direct',
            payload={
                'visitor_id': visitor_id,
                'trait_key': trait_key,
                'trait_category': trait_category,
                'source_event_id': source_event_id,
            },
        )
    except Exception:
        pass


async def get_visitor_traits(visitor_id: str, limit: int = 20) -> list[VisitorTrait]:
    db = await _connection.get_db()
    cursor = await db.execute(
        """SELECT * FROM visitor_traits
           WHERE visitor_id = ? AND status = 'active'
           ORDER BY observed_at DESC LIMIT ?""",
        (visitor_id, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_trait(r) for r in rows]


async def get_all_active_traits() -> list[VisitorTrait]:
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM visitor_traits WHERE status IN ('active', 'anomaly')"
    )
    rows = await cursor.fetchall()
    return [_row_to_trait(r) for r in rows]


async def get_trait_history(visitor_id: str, category: str, key: str) -> list[VisitorTrait]:
    db = await _connection.get_db()
    cursor = await db.execute(
        """SELECT * FROM visitor_traits
           WHERE visitor_id = ? AND trait_category = ? AND trait_key = ?
           ORDER BY observed_at DESC""",
        (visitor_id, category, key)
    )
    rows = await cursor.fetchall()
    return [_row_to_trait(r) for r in rows]


async def update_trait_stability(trait_id: str, stability: float):
    await _connection._exec_write("UPDATE visitor_traits SET stability = ? WHERE id = ?", (stability, trait_id))


async def update_trait_status(trait_id: str, status: str):
    await _connection._exec_write("UPDATE visitor_traits SET status = ? WHERE id = ?", (status, trait_id))


def _row_to_trait(row) -> VisitorTrait:
    return VisitorTrait(
        id=row['id'], visitor_id=row['visitor_id'],
        trait_category=row['trait_category'], trait_key=row['trait_key'],
        trait_value=row['trait_value'],
        observed_at=datetime.fromisoformat(row['observed_at']),
        source_event_id=row['source_event_id'],
        confidence=row['confidence'], stability=row['stability'],
        status=row['status'], notes=row['notes'],
    )


# ─── Totems ───

async def get_totems(visitor_id: str = None, min_weight: float = 0.0,
                     limit: int = 10) -> list[Totem]:
    db = await _connection.get_db()
    if visitor_id:
        cursor = await db.execute(
            """SELECT * FROM totems
               WHERE visitor_id = ? AND weight >= ?
               ORDER BY weight DESC LIMIT ?""",
            (visitor_id, min_weight, limit)
        )
    else:
        cursor = await db.execute(
            """SELECT * FROM totems
               WHERE visitor_id IS NULL AND weight >= ?
               ORDER BY weight DESC LIMIT ?""",
            (min_weight, limit)
        )
    rows = await cursor.fetchall()
    return [_row_to_totem(r) for r in rows]


async def insert_totem(visitor_id: str = None, entity: str = '',
                       weight: float = 0.5, context: str = '',
                       category: str = 'general', source_event_id: str = None):
    totem_id = str(uuid.uuid4())
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        """INSERT INTO totems
           (id, visitor_id, entity, weight, context, category, first_seen, last_referenced, source_event_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (totem_id, visitor_id, entity, weight, context, category, now, now, source_event_id)
    )
    await _log_memory_write_event(
        memory_type='semantic',
        content_text=f"{entity} {context}".strip(),
        location='totems',
        fact_id=totem_id,
        payload={
            'visitor_id': visitor_id,
            'entity': entity,
            'weight': weight,
            'category': category,
            'source_event_id': source_event_id,
            'first_seen': now,
        },
    )


async def update_totem(entity: str, visitor_id: str = None,
                       weight: float = None, last_referenced: datetime = None):
    updates = []
    vals = []
    if weight is not None:
        updates.append("weight = ?")
        vals.append(weight)
    if last_referenced is not None:
        updates.append("last_referenced = ?")
        vals.append(last_referenced.isoformat())
    if updates:
        if visitor_id is not None:
            where = "WHERE entity = ? AND visitor_id = ?"
            vals.extend([entity, visitor_id])
        else:
            where = "WHERE entity = ? AND visitor_id IS NULL"
            vals.append(entity)
        await _connection._exec_write(f"UPDATE totems SET {', '.join(updates)} {where}", tuple(vals))


def _row_to_totem(row) -> Totem:
    return Totem(
        id=row['id'], entity=row['entity'], weight=row['weight'],
        visitor_id=row['visitor_id'], context=row['context'],
        category=row['category'],
        first_seen=datetime.fromisoformat(row['first_seen']) if row['first_seen'] else None,
        last_referenced=datetime.fromisoformat(row['last_referenced']) if row['last_referenced'] else None,
        source_event_id=row['source_event_id'],
    )


async def get_all_totems(limit: int = 100) -> list[Totem]:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM totems ORDER BY weight DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    return [_row_to_totem(r) for r in rows]


# ─── Collection Items ───

async def insert_collection_item(item: dict):
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        """INSERT INTO collection_items
           (id, item_type, title, url, description, location, origin, gifted_by,
            her_feeling, emotional_tags, display_note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item.get('id', str(uuid.uuid4())), item['item_type'], item['title'],
         item.get('url'), item.get('description'), item.get('location', 'shelf'),
         item.get('origin', 'appeared'), item.get('gifted_by'),
         item.get('her_feeling'), json.dumps(item.get('emotional_tags', [])),
         item.get('display_note'), item.get('created_at', now))
    )


async def search_collection(query: str = '', limit: int = 3) -> list[CollectionItem]:
    db = await _connection.get_db()
    if query:
        cursor = await db.execute(
            """SELECT * FROM collection_items
               WHERE title LIKE ? OR description LIKE ? OR her_feeling LIKE ?
               ORDER BY created_at DESC LIMIT ?""",
            (f'%{query}%', f'%{query}%', f'%{query}%', limit)
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM collection_items ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    rows = await cursor.fetchall()
    return [_row_to_collection(r) for r in rows]


def _row_to_collection(row) -> CollectionItem:
    return CollectionItem(
        id=row['id'], item_type=row['item_type'], title=row['title'],
        url=row['url'], description=row['description'], location=row['location'],
        origin=row['origin'], gifted_by=row['gifted_by'],
        her_feeling=row['her_feeling'],
        emotional_tags=json.loads(row['emotional_tags']) if row['emotional_tags'] else [],
        display_note=row['display_note'],
        created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
    )


async def get_collection_by_location(location: str) -> list[CollectionItem]:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM collection_items WHERE location = ? ORDER BY created_at DESC",
        (location,)
    )
    rows = await cursor.fetchall()
    return [_row_to_collection(r) for r in rows]


# ─── Journal ───

async def insert_journal(content: str, mood: str = None, tags: list = None,
                         day_alive: int = None) -> str:
    jid = str(uuid.uuid4())
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        """INSERT INTO journal_entries (id, content, mood, day_alive, tags, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (jid, content, mood, day_alive, json.dumps(tags or []), now)
    )
    tagset = {str(t).lower() for t in (tags or [])}
    source = 'sleep' if tagset & {'sleep_reflection', 'nap_reflection', 'sleep_cycle', 'daily', 'quiet_day'} else _infer_memory_source()
    memory_type = 'summary' if tagset & {'sleep_cycle', 'daily', 'quiet_day'} else 'episodic'
    sleep_session_id = f"sleep-{clock.now().date().isoformat()}" if source == 'sleep' else None
    await _log_memory_write_event(
        memory_type=memory_type,
        content_text=content or '',
        location='journal_entries',
        source=source,
        sleep_session_id=sleep_session_id,
        fact_id=jid,
        payload={
            'mood': mood,
            'tags': tags or [],
            'day_alive': day_alive,
            'created_at': now,
        },
    )
    return jid


async def get_recent_journal(limit: int = 2) -> list[JournalEntry]:
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM journal_entries ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    return [JournalEntry(
        id=r['id'], content=r['content'], mood=r['mood'],
        day_alive=r['day_alive'],
        tags=json.loads(r['tags']) if r['tags'] else [],
        created_at=datetime.fromisoformat(r['created_at']) if r['created_at'] else None,
    ) for r in rows]


async def get_all_journal() -> list[JournalEntry]:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM journal_entries ORDER BY created_at ASC"
    )
    rows = await cursor.fetchall()
    return [JournalEntry(
        id=r['id'], content=r['content'], mood=r['mood'],
        day_alive=r['day_alive'],
        tags=json.loads(r['tags']) if r['tags'] else [],
        created_at=datetime.fromisoformat(r['created_at']) if r['created_at'] else None,
    ) for r in rows]


# ─── Daily Summary ───

async def insert_daily_summary(summary: dict):
    """Insert a lightweight daily summary index.

    The DB column ``summary_bullets`` (legacy name) stores the moment index
    as JSON: {"moment_count": N, "moment_ids": [...], "journal_entry_ids": [...]}.
    The ``journal_entry_id`` column is always NULL — individual reflections
    are stored as separate journal entries since TASK-007.
    """
    now = clock.now_utc().isoformat()
    index_data = {
        'moment_count': summary.get('moment_count', 0),
        'moment_ids': summary.get('moment_ids', []),
        'journal_entry_ids': summary.get('journal_entry_ids', []),
    }
    summary_id = str(uuid.uuid4())
    await _connection._exec_write(
        """INSERT INTO daily_summaries
           (id, day_number, date, journal_entry_id, summary_bullets, emotional_arc, notable_totems, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (summary_id, summary.get('day_number'), summary.get('date'),
         None, json.dumps(index_data),
         summary.get('emotional_arc'), json.dumps(summary.get('notable_totems', [])), now)
    )
    await _log_memory_write_event(
        memory_type='summary',
        content_text=f"{summary.get('emotional_arc', '')} {json.dumps(index_data, ensure_ascii=True)}".strip(),
        location='daily_summaries',
        source='sleep',
        sleep_session_id=f"sleep-{clock.now().date().isoformat()}",
        fact_id=summary_id,
        payload={
            'day_number': summary.get('day_number'),
            'date': summary.get('date'),
            'moment_count': summary.get('moment_count', 0),
            'created_at': now,
        },
    )


async def get_daily_summary_for_today() -> Optional[DailySummary]:
    """Check if a daily summary already exists for today (JST).

    Returns a DailySummary dataclass with the moment index unpacked
    from the legacy ``summary_bullets`` JSON column.
    """
    conn = await _connection.get_db()
    today_jst = clock.now().date().isoformat()
    cursor = await conn.execute(
        "SELECT * FROM daily_summaries WHERE date = ?",
        (today_jst,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_daily_summary(row)


def _row_to_daily_summary(row) -> DailySummary:
    """Convert a DB row to a DailySummary dataclass.

    The legacy ``summary_bullets`` column stores the moment index as JSON.
    The legacy ``journal_entry_id`` column is always NULL.
    """
    index_data = json.loads(row['summary_bullets']) if row['summary_bullets'] else {}
    return DailySummary(
        id=row['id'],
        day_number=row['day_number'],
        date=row['date'],
        moment_count=index_data.get('moment_count', 0),
        moment_ids=index_data.get('moment_ids', []),
        journal_entry_ids=index_data.get('journal_entry_ids', []),
        emotional_arc=row['emotional_arc'],
        notable_totems=json.loads(row['notable_totems']) if row['notable_totems'] else [],
        created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
    )


# ─── Conversation Log ───

async def append_conversation(visitor_id: str, role: str, text: str):
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        "INSERT INTO conversation_log (id, visitor_id, role, text, ts) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), visitor_id, role, text, now)
    )


async def mark_session_boundary(visitor_id: str):
    """Insert a session boundary marker so get_recent_conversation only returns current session."""
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        "INSERT INTO conversation_log (id, visitor_id, role, text, ts) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), visitor_id, 'system', '__session_boundary__', now)
    )


async def get_recent_conversation(visitor_id: str, limit: int = 10) -> list[dict]:
    """Get recent conversation for visitor, scoped to current session."""
    conn = await _connection.get_db()
    # Find the most recent session boundary
    cursor = await conn.execute(
        "SELECT ts FROM conversation_log WHERE visitor_id = ? AND role = 'system' "
        "AND text = '__session_boundary__' ORDER BY ts DESC LIMIT 1",
        (visitor_id,)
    )
    boundary = await cursor.fetchone()

    if boundary:
        cursor = await conn.execute(
            "SELECT role, text FROM conversation_log "
            "WHERE visitor_id = ? AND ts > ? AND NOT (role = 'system' AND text = '__session_boundary__') "
            "ORDER BY ts DESC LIMIT ?",
            (visitor_id, boundary['ts'], limit)
        )
    else:
        cursor = await conn.execute(
            "SELECT role, text FROM conversation_log WHERE visitor_id = ? ORDER BY ts DESC LIMIT ?",
            (visitor_id, limit)
        )
    rows = await cursor.fetchall()
    return [{'role': r['role'], 'text': r['text']} for r in reversed(rows)]


# ─── Self Knowledge ───

async def get_self_discoveries() -> str:
    db = await _connection.get_db()
    cursor = await db.execute(
        """SELECT content FROM journal_entries
           WHERE tags LIKE '%identity%' OR tags LIKE '%self_discovery%'
           ORDER BY created_at DESC LIMIT 5"""
    )
    rows = await cursor.fetchall()
    return "\n".join(r['content'][:200] for r in rows) if rows else ""


async def append_self_discovery(text: str):
    await insert_journal(content=text, tags=['self_discovery'])


# ─── Taste Knowledge ───

async def get_taste_knowledge(domain: str) -> str:
    db = await _connection.get_db()
    cursor = await db.execute(
        """SELECT title, her_feeling FROM collection_items
           WHERE item_type = ? OR emotional_tags LIKE ?
           ORDER BY created_at DESC LIMIT 5""",
        (domain, f'%{domain}%')
    )
    rows = await cursor.fetchall()
    if not rows:
        return ""
    return "\n".join(f"- {r['title']}: {r['her_feeling'] or ''}" for r in rows)


# ─── Flashbulb Count ───

async def get_flashbulb_count_today() -> int:
    db = await _connection.get_db()
    today_jst = clock.now().date().isoformat()
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM cycle_log WHERE date(ts, '+9 hours') = ? AND token_budget >= 10000",
        (today_jst,)
    )
    row = await cursor.fetchone()
    return row['cnt'] if row else 0


# ─── Peek Queries ───

async def get_visitor_count_today() -> int:
    conn = await _connection.get_db()
    today_jst = clock.now().date().isoformat()
    cursor = await conn.execute(
        "SELECT COUNT(DISTINCT source) as cnt FROM events "
        "WHERE event_type = 'visitor_connect' AND date(ts, '+9 hours') = ?",
        (today_jst,)
    )
    row = await cursor.fetchone()
    return row['cnt'] if row else 0


async def get_days_alive() -> int:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT MIN(created_at) as first FROM events"
    )
    row = await cursor.fetchone()
    if not row or not row['first']:
        return 0
    first = datetime.fromisoformat(row['first'])
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    now = clock.now_utc()
    return max(1, (now - first).days + 1)


# ─── Day Memory ───

_MAX_DAY_MEMORIES = 30


async def get_max_event_salience_dynamic(event_ids: list[str]) -> float:
    """Get the maximum salience_dynamic from a list of event IDs.

    Used by day_memory to incorporate TASK-045 salience engine signals
    into moment scoring. Returns 0.0 if no events found or all are zero.
    """
    if not event_ids:
        return 0.0
    conn = await _connection.get_db()
    placeholders = ', '.join('?' for _ in event_ids)
    cursor = await conn.execute(
        f"SELECT MAX(salience_dynamic) as max_sd FROM events WHERE id IN ({placeholders})",
        tuple(event_ids)
    )
    row = await cursor.fetchone()
    return float(row['max_sd']) if row and row['max_sd'] else 0.0


async def insert_day_memory(moment) -> None:
    """Insert a day memory entry. Enforces MAX_DAY_MEMORIES cap.

    Atomic: count + evict + insert run inside a single transaction to
    prevent concurrent inserts from overshooting the cap.
    """
    async with transaction():
        conn = await _connection.get_db()

        cursor = await conn.execute("SELECT COUNT(*) as cnt FROM day_memory")
        row = await cursor.fetchone()
        count = row['cnt'] if row else 0

        if count >= _MAX_DAY_MEMORIES:
            # Evict lowest-salience entry
            await conn.execute(
                "DELETE FROM day_memory WHERE id = ("
                "  SELECT id FROM day_memory ORDER BY salience ASC LIMIT 1"
                ")"
            )

        await conn.execute(
            """INSERT INTO day_memory
               (id, ts, salience, moment_type, visitor_id, summary, raw_refs, tags, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (moment.id, moment.ts.isoformat(), moment.salience, moment.moment_type,
             moment.visitor_id, moment.summary, json.dumps(moment.raw_refs),
             json.dumps(moment.tags), clock.now_utc().isoformat())
        )
        # commit is handled by transaction().__aexit__
    await _log_memory_write_event(
        memory_type='episodic',
        content_text=moment.summary or '',
        location='day_memory',
        source='awake',
        cycle_id=(
            moment.raw_refs.get('cycle_id')
            if isinstance(getattr(moment, 'raw_refs', None), dict)
            else None
        ),
        fact_id=moment.id,
        payload={
            'moment_type': moment.moment_type,
            'salience': moment.salience,
            'visitor_id': moment.visitor_id,
            'tags': moment.tags,
            'raw_refs': moment.raw_refs,
        },
    )


def _jst_today_start_utc() -> str:
    """Return start of today (JST) as UTC ISO string for day_memory filtering.

    Day memory is scoped to the current JST day. This computes midnight JST
    converted to UTC so we can filter the UTC timestamps stored in day_memory.
    """
    now_jst = clock.now()
    start_of_day_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_day_utc = start_of_day_jst.astimezone(timezone.utc)
    return start_of_day_utc.isoformat()


async def get_day_memory(
    visitor_id: str = None,
    limit: int = 3,
    min_salience: float = 0.3,
) -> list:
    """Get today's day memory entries, optionally filtered by visitor and salience."""
    conn = await _connection.get_db()
    today_start = _jst_today_start_utc()
    if visitor_id:
        cursor = await conn.execute(
            """SELECT * FROM day_memory
               WHERE visitor_id = ? AND salience >= ? AND processed_at IS NULL
                     AND ts >= ?
               ORDER BY salience DESC LIMIT ?""",
            (visitor_id, min_salience, today_start, limit)
        )
    else:
        cursor = await conn.execute(
            """SELECT * FROM day_memory
               WHERE salience >= ? AND processed_at IS NULL
                     AND ts >= ?
               ORDER BY salience DESC LIMIT ?""",
            (min_salience, today_start, limit)
        )
    rows = await cursor.fetchall()
    return [_row_to_day_memory(r) for r in rows]


async def get_day_memory_dashboard(
    limit: int = 20,
    days: int = 7,
    min_salience: float = 0.3,
) -> list:
    """Get recent day memory for dashboard display (rolling window, includes processed)."""
    conn = await _connection.get_db()
    now_jst = clock.now()
    window_start_jst = now_jst - timedelta(days=days)
    window_start_utc = window_start_jst.astimezone(timezone.utc).isoformat()
    cursor = await conn.execute(
        """SELECT * FROM day_memory
           WHERE salience >= ? AND ts >= ?
           ORDER BY ts DESC LIMIT ?""",
        (min_salience, window_start_utc, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_day_memory(r) for r in rows]


async def get_unprocessed_day_memory(
    min_salience: float = 0.4,
    limit: int = 7,
) -> list:
    """Get unprocessed day memory entries for night sleep consolidation.

    Excludes moments already processed by nap consolidation (nap_processed=1).
    No date filter — sleep runs at 03:00 JST and must consolidate
    moments from the entire prior waking period (which spans two calendar
    days, e.g. 06:00 JST yesterday through 02:00 JST today). The
    delete_stale_day_memory() safety net prevents unbounded accumulation.
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM day_memory
           WHERE processed_at IS NULL
                 AND COALESCE(nap_processed, 0) = 0
                 AND salience >= ?
           ORDER BY salience DESC LIMIT ?""",
        (min_salience, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_day_memory(r) for r in rows]


async def get_top_unprocessed_moments(limit: int = 3) -> list:
    """Get top unprocessed moments by salience for nap consolidation.

    Excludes moments already processed by night sleep OR a previous nap.
    No salience floor — naps process whatever is available.
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM day_memory
           WHERE processed_at IS NULL
                 AND COALESCE(nap_processed, 0) = 0
           ORDER BY salience DESC LIMIT ?""",
        (limit,)
    )
    rows = await cursor.fetchall()
    return [_row_to_day_memory(r) for r in rows]


async def mark_moments_nap_processed(moment_ids: list[str]) -> None:
    """Mark moments as processed by nap consolidation.

    These moments won't be re-processed during night sleep.
    """
    if not moment_ids:
        return
    placeholders = ', '.join('?' for _ in moment_ids)
    await _connection._exec_write(
        f"UPDATE day_memory SET nap_processed = 1 WHERE id IN ({placeholders})",
        tuple(moment_ids)
    )


async def mark_day_memory_processed(moment_id: str) -> None:
    """Stamp processed_at on a day memory entry."""
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        "UPDATE day_memory SET processed_at = ? WHERE id = ?",
        (now, moment_id)
    )


async def increment_day_memory_retry(moment_id: str) -> None:
    """Increment retry_count for a failed day memory entry.

    This is a standalone write — commits even when the calling
    transaction has rolled back."""
    await _connection._exec_write(
        "UPDATE day_memory SET retry_count = retry_count + 1 WHERE id = ?",
        (moment_id,)
    )


async def delete_processed_day_memory() -> None:
    """Delete day_memory rows where processed_at IS NOT NULL.

    Calls _exec_write() directly — _exec_write() already acquires
    _write_lock when called outside a transaction. Do NOT double-lock."""
    await _connection._exec_write(
        "DELETE FROM day_memory WHERE processed_at IS NOT NULL"
    )


async def delete_stale_day_memory(max_age_days: int = 2) -> None:
    """Delete day_memory rows older than max_age_days, regardless of status.

    Safety net: prevents unprocessed moments from leaking across day
    boundaries if sleep didn't process them (e.g. only top-K were selected).
    """
    cutoff = (clock.now_utc() - timedelta(days=max_age_days)).isoformat()
    await _connection._exec_write(
        "DELETE FROM day_memory WHERE ts < ?",
        (cutoff,)
    )


def _row_to_day_memory(row):
    """Convert a DB row to a DayMemoryEntry."""
    from pipeline.day_memory import DayMemoryEntry
    # nap_processed column may not exist in older DBs (pre-migration-015)
    try:
        nap_flag = bool(row['nap_processed'])
    except (IndexError, KeyError):
        nap_flag = False
    return DayMemoryEntry(
        id=row['id'],
        ts=datetime.fromisoformat(row['ts']),
        salience=row['salience'],
        moment_type=row['moment_type'],
        visitor_id=row['visitor_id'],
        summary=row['summary'],
        raw_refs=json.loads(row['raw_refs']) if row['raw_refs'] else {},
        tags=json.loads(row['tags']) if row['tags'] else [],
        retry_count=row['retry_count'],
        processed_at=(datetime.fromisoformat(row['processed_at'])
                       if row['processed_at'] else None),
        nap_processed=nap_flag,
    )


# ─── Window UI Support ───

async def insert_text_fragment(
    content: str,
    fragment_type: str,
    cycle_id: str = None,
    thread_id: str = None,
    visitor_id: str = None,
) -> str:
    """Insert a text fragment for the window text stream."""
    frag_id = str(uuid.uuid4())
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        """INSERT INTO text_fragments
           (id, content, fragment_type, cycle_id, thread_id, visitor_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (frag_id, content, fragment_type, cycle_id, thread_id, visitor_id, now)
    )
    await _log_memory_write_event(
        memory_type='episodic',
        content_text=content or '',
        location='text_fragments',
        cycle_id=cycle_id,
        source=_infer_memory_source(),
        fact_id=frag_id,
        payload={
            'fragment_type': fragment_type,
            'thread_id': thread_id,
            'visitor_id': visitor_id,
            'created_at': now,
        },
    )
    return frag_id


async def get_recent_text_fragments(limit: int = 8) -> list[dict]:
    """Get recent text fragments for window display."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM text_fragments ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    rows = await cursor.fetchall()
    return [{
        'id': r['id'],
        'content': r['content'],
        'fragment_type': r['fragment_type'],
        'cycle_id': r['cycle_id'],
        'thread_id': r['thread_id'],
        'visitor_id': r['visitor_id'],
        'created_at': r['created_at'],
    } for r in rows]


async def get_shelf_assignments() -> list[dict]:
    """Get all shelf assignments for scene composition."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM shelf_assignments ORDER BY assigned_at ASC"
    )
    rows = await cursor.fetchall()
    return [{
        'slot_id': r['slot_id'],
        'item_id': r['item_id'],
        'item_description': r['item_description'],
        'sprite_filename': r['sprite_filename'],
        'assigned_at': r['assigned_at'],
    } for r in rows]


async def assign_shelf_slot(item_id: str, description: str,
                            sprite_filename: str = None) -> Optional[str]:
    """Assign an item to the next available shelf slot. Returns slot_id or None."""
    from pipeline.scene import SHELF_SLOTS

    conn = await _connection.get_db()
    cursor = await conn.execute("SELECT slot_id FROM shelf_assignments")
    occupied = {r['slot_id'] for r in await cursor.fetchall()}

    slot_id = None
    for sid in SHELF_SLOTS:
        if sid not in occupied:
            slot_id = sid
            break

    if not slot_id:
        return None

    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        """INSERT INTO shelf_assignments
           (slot_id, item_id, item_description, sprite_filename, assigned_at)
           VALUES (?, ?, ?, ?, ?)""",
        (slot_id, item_id, description, sprite_filename, now)
    )
    return slot_id


async def update_shelf_sprite(slot_id: str, sprite_filename: str):
    """Update sprite filename after generation completes."""
    await _connection._exec_write(
        "UPDATE shelf_assignments SET sprite_filename = ? WHERE slot_id = ?",
        (sprite_filename, slot_id)
    )


# ─── Chat Tokens ───

async def create_chat_token(
    token: str,
    display_name: str,
    uses_remaining: int = None,
    expires_at: datetime = None,
):
    """Create a new chat invite token."""
    now = clock.now_utc().isoformat()
    expires_str = expires_at.isoformat() if expires_at else None
    await _connection._exec_write(
        """INSERT INTO chat_tokens
           (token, display_name, uses_remaining, expires_at, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (token, display_name, uses_remaining, expires_str, now)
    )


async def validate_chat_token(token: str) -> Optional[dict]:
    """Validate a chat token. Returns token info or None if invalid.

    NOTE: This only checks validity. To atomically validate AND consume
    a use, call validate_and_consume_chat_token() instead.
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM chat_tokens WHERE token = ?", (token,)
    )
    row = await cursor.fetchone()
    if not row:
        return None

    if row['expires_at']:
        expires = datetime.fromisoformat(row['expires_at'])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if clock.now_utc() > expires:
            return None

    if row['uses_remaining'] is not None and row['uses_remaining'] <= 0:
        return None

    return {
        'token': row['token'],
        'display_name': row['display_name'],
        'uses_remaining': row['uses_remaining'],
    }


async def validate_and_consume_chat_token(token: str) -> Optional[dict]:
    """Atomically validate and consume one use of a chat token.

    Uses UPDATE ... WHERE uses_remaining > 0 to prevent race conditions.
    Returns token info if valid and consumed, or None if invalid/exhausted.
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM chat_tokens WHERE token = ?", (token,)
    )
    row = await cursor.fetchone()
    if not row:
        return None

    if row['expires_at']:
        expires = datetime.fromisoformat(row['expires_at'])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if clock.now_utc() > expires:
            return None

    if row['uses_remaining'] is None:
        return {
            'token': row['token'],
            'display_name': row['display_name'],
            'uses_remaining': None,
        }

    # Atomic decrement under _write_lock — only succeeds if uses_remaining > 0.
    # Must hold the lock so we don't commit unrelated in-flight transactions.
    async with _write_lock:
        result = await conn.execute(
            """UPDATE chat_tokens SET uses_remaining = uses_remaining - 1
               WHERE token = ? AND uses_remaining > 0""",
            (token,)
        )
        await conn.commit()

    if result.rowcount == 0:
        return None

    return {
        'token': row['token'],
        'display_name': row['display_name'],
        'uses_remaining': row['uses_remaining'] - 1,
    }


async def consume_chat_token(token: str):
    """Decrement uses_remaining for a token.

    DEPRECATED: Use validate_and_consume_chat_token() for atomic operations.
    """
    await _connection._exec_write(
        """UPDATE chat_tokens SET uses_remaining = uses_remaining - 1
           WHERE token = ? AND uses_remaining IS NOT NULL AND uses_remaining > 0""",
        (token,)
    )


# ─── Cold Memory (Phase 2) ───

async def insert_cold_embedding(
    source_type: str,
    source_id: str,
    text_content: str,
    ts: datetime,
    embedding: list[float],
    embed_model: str,
) -> None:
    """Insert a vector embedding into cold_memory_vec.

    Uses _write_lock directly — vec0 virtual tables don't support
    our transaction() wrapper the same way.

    Includes dedupe guard: skips insert if (source_type, source_id)
    already exists. This prevents double-embedding on retry.
    """
    import sqlite_vec

    ts_iso = ts.isoformat() if isinstance(ts, datetime) else str(ts)
    text_truncated = text_content[:500] if text_content else ''
    vec_blob = sqlite_vec.serialize_float32(embedding)

    async with _write_lock:
        conn = await _connection.get_db()

        # Dedupe guard: skip if already embedded
        cursor = await conn.execute(
            "SELECT 1 FROM cold_memory_vec WHERE source_type = ? AND source_id = ?",
            (source_type, source_id)
        )
        if await cursor.fetchone():
            return  # already embedded

        await conn.execute(
            """INSERT INTO cold_memory_vec
               (embedding, source_type, source_id, text_content, ts_iso, embed_model)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (vec_blob, source_type, source_id, text_truncated, ts_iso, embed_model)
        )
        await conn.commit()


async def get_unembedded_conversations(limit: int = 50) -> list[dict]:
    """Find conversation_log rows not yet embedded in cold_memory_vec.

    Skips system boundary markers. Returns oldest-first for chronological
    embedding order. Uses NOT EXISTS (safer than NOT IN with NULLs).
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT c.id, c.visitor_id, c.role, c.text, c.ts
           FROM conversation_log c
           WHERE c.role IN ('visitor', 'shopkeeper')
             AND NOT EXISTS (
                 SELECT 1 FROM cold_memory_vec v
                 WHERE v.source_id = c.id
                   AND v.source_type = 'conversation'
             )
           ORDER BY c.ts ASC LIMIT ?""",
        (limit,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_unembedded_monologues(limit: int = 50) -> list[dict]:
    """Find cycle_log rows with internal monologue not yet embedded.

    Skips entries with NULL or very short monologues (< 10 chars).
    Returns oldest-first. Uses NOT EXISTS (safer than NOT IN with NULLs).
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT c.id, c.internal_monologue, c.dialogue, c.ts
           FROM cycle_log c
           WHERE c.internal_monologue IS NOT NULL
             AND LENGTH(c.internal_monologue) > 10
             AND NOT EXISTS (
                 SELECT 1 FROM cold_memory_vec v
                 WHERE v.source_id = c.id
                   AND v.source_type = 'monologue'
             )
           ORDER BY c.ts ASC LIMIT ?""",
        (limit,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def vector_search_cold_memory(
    query_embedding: list[float],
    limit: int = 3,
    exclude_after_iso: Optional[str] = None,
) -> list[dict]:
    """KNN search over cold_memory_vec.

    Returns nearest neighbors with source_type, source_id, text_content,
    ts_iso, and distance. Optional timestamp exclusion for filtering out
    today's entries.
    """
    import sqlite_vec

    conn = await _connection.get_db()
    vec_blob = sqlite_vec.serialize_float32(query_embedding)

    # sqlite-vec KNN query: WHERE embedding MATCH ? AND k = ?
    # Note: metadata filtering (source_type) can be added to WHERE clause.
    # Auxiliary columns (ts_iso) cannot be filtered in WHERE — we filter in Python.
    cursor = await conn.execute(
        """SELECT source_type, source_id, text_content, ts_iso,
                  embed_model, distance
           FROM cold_memory_vec
           WHERE embedding MATCH ? AND k = ?""",
        (vec_blob, limit * 3 if exclude_after_iso else limit)
    )
    rows = await cursor.fetchall()

    results = []
    for r in rows:
        # Filter out entries from today if requested
        if exclude_after_iso and r['ts_iso'] >= exclude_after_iso:
            continue
        results.append(dict(r))
        if len(results) >= limit:
            break

    return results


async def get_conversation_context(
    message_id: str,
    before: int = 2,
    after: int = 2,
) -> list[dict]:
    """Fetch surrounding conversation turns for context enrichment.

    Returns ±N messages around the given message_id, ordered by timestamp.
    """
    conn = await _connection.get_db()

    # Get the target message's timestamp and visitor_id
    cursor = await conn.execute(
        "SELECT ts, visitor_id FROM conversation_log WHERE id = ?",
        (message_id,)
    )
    target = await cursor.fetchone()
    if not target:
        return []

    # Get messages before
    cursor = await conn.execute(
        """SELECT role, text, ts FROM conversation_log
           WHERE visitor_id = ? AND ts <= ? AND id != ?
             AND role IN ('visitor', 'shopkeeper')
           ORDER BY ts DESC LIMIT ?""",
        (target['visitor_id'], target['ts'], message_id, before)
    )
    before_rows = list(reversed(await cursor.fetchall()))

    # Get the target message itself
    cursor = await conn.execute(
        "SELECT role, text, ts FROM conversation_log WHERE id = ?",
        (message_id,)
    )
    target_row = await cursor.fetchone()

    # Get messages after
    cursor = await conn.execute(
        """SELECT role, text, ts FROM conversation_log
           WHERE visitor_id = ? AND ts > ?
             AND role IN ('visitor', 'shopkeeper')
           ORDER BY ts ASC LIMIT ?""",
        (target['visitor_id'], target['ts'], after)
    )
    after_rows = await cursor.fetchall()

    context = []
    for r in before_rows:
        context.append({'role': r['role'], 'text': r['text']})
    if target_row:
        context.append({'role': target_row['role'], 'text': target_row['text']})
    for r in after_rows:
        context.append({'role': r['role'], 'text': r['text']})

    return context


async def get_cycle_by_id(cycle_id: str) -> Optional[dict]:
    """Fetch a single cycle_log entry by ID."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM cycle_log WHERE id = ?",
        (cycle_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_cold_embedding_count() -> int:
    """Return total number of embeddings in cold_memory_vec."""
    conn = await _connection.get_db()
    try:
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM cold_memory_vec"
        )
        row = await cursor.fetchone()
        return row['cnt'] if row else 0
    except Exception:
        return 0


# ── Visitor presence (multi-slot, TASK-013) ──

async def add_visitor_present(visitor_id: str, connection_type: str = 'tcp'):
    """Add a visitor to the shop (or update if already present)."""
    await _connection._exec_write(
        """INSERT INTO visitors_present (visitor_id, connection_type, status, entered_at, last_activity)
           VALUES (?, ?, 'browsing', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
           ON CONFLICT(visitor_id) DO UPDATE SET
               connection_type = excluded.connection_type,
               status = 'browsing',
               last_activity = CURRENT_TIMESTAMP""",
        (visitor_id, connection_type),
    )


async def remove_visitor_present(visitor_id: str):
    """Remove a visitor from the shop."""
    await _connection._exec_write(
        "DELETE FROM visitors_present WHERE visitor_id = ?",
        (visitor_id,),
    )


async def get_visitors_present() -> list:
    """Get all visitors currently in the shop."""
    from models.state import VisitorPresence
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT visitor_id, status, entered_at, last_activity, connection_type FROM visitors_present"
    )
    rows = await cursor.fetchall()
    return [
        VisitorPresence(
            visitor_id=r['visitor_id'],
            status=r['status'],
            entered_at=r['entered_at'],
            last_activity=r['last_activity'],
            connection_type=r['connection_type'],
        )
        for r in rows
    ]


async def update_visitor_present(visitor_id: str, **kwargs):
    """Update fields on a visitor's presence record.

    Accepts keyword args matching visitors_present columns:
    status, last_activity, connection_type.
    """
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = tuple(kwargs.values())
    await _connection._exec_write(
        f"UPDATE visitors_present SET {sets} WHERE visitor_id = ?",
        vals + (visitor_id,),
    )


async def clear_all_visitors_present():
    """Clear all visitor presence records (used on server startup)."""
    await _connection._exec_write("DELETE FROM visitors_present")


# ── Internal conflicts ──

async def get_recent_internal_conflicts(limit: int = 5) -> list[dict]:
    """Get recent internal_conflict moments from day_memories."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, ts, salience, summary, tags
           FROM day_memories
           WHERE moment_type = 'internal_conflict'
           ORDER BY ts DESC
           LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
