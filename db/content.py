"""db.content — Threads, arbiter state, and content pool."""

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import clock
from models.state import Thread
import db.connection as _connection


# ─── Threads ───

def _row_to_thread(row) -> Thread:
    return Thread(
        id=row['id'],
        thread_type=row['thread_type'],
        title=row['title'],
        status=row['status'],
        priority=row['priority'],
        content=row['content'],
        resolution=row['resolution'],
        created_at=(datetime.fromisoformat(row['created_at'])
                    if row['created_at'] else None),
        last_touched=(datetime.fromisoformat(row['last_touched'])
                      if row['last_touched'] else None),
        touch_count=row['touch_count'] or 0,
        touch_reason=row['touch_reason'],
        target_date=row['target_date'],
        source_visitor_id=row['source_visitor_id'],
        source_event_id=row['source_event_id'],
        tags=json.loads(row['tags']) if row['tags'] else [],
    )


async def get_active_threads(limit: int = 3) -> list[Thread]:
    """Get active/open threads sorted by priority then recency."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM threads
           WHERE status IN ('open', 'active')
           ORDER BY priority DESC, last_touched DESC
           LIMIT ?""",
        (limit,)
    )
    rows = await cursor.fetchall()
    return [_row_to_thread(r) for r in rows]


async def get_thread_by_id(thread_id: str) -> Optional[Thread]:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM threads WHERE id = ?", (thread_id,)
    )
    row = await cursor.fetchone()
    return _row_to_thread(row) if row else None


async def get_thread_by_title(title: str) -> Optional[Thread]:
    """Exact case-insensitive match only. Returns None if 0 or >1 matches."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM threads WHERE LOWER(title) = LOWER(?) AND status != 'archived'",
        (title,)
    )
    rows = await cursor.fetchall()
    if len(rows) != 1:
        return None  # ambiguous or not found — no silent wrong-thread writes
    return _row_to_thread(rows[0])


async def create_thread(thread_type: str, title: str, **kwargs) -> Thread:
    """Create a new thread. Returns the created Thread."""
    tid = str(uuid.uuid4())
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        """INSERT INTO threads
           (id, thread_type, title, status, priority, content, created_at,
            last_touched, touch_count, tags, source_visitor_id, source_event_id,
            target_date)
           VALUES (?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
        (tid, thread_type, title,
         kwargs.get('priority', 0.5),
         kwargs.get('content', ''),
         now, now,
         json.dumps(kwargs.get('tags', [])),
         kwargs.get('source_visitor_id'),
         kwargs.get('source_event_id'),
         kwargs.get('target_date'))
    )
    return await get_thread_by_id(tid)


async def touch_thread(thread_id: str, reason: str,
                       content: str = None, status: str = None):
    """Update a thread's touch timestamp, reason, and optionally content/status."""
    now = clock.now_utc().isoformat()
    updates = ["last_touched = ?", "touch_count = touch_count + 1",
               "touch_reason = ?"]
    vals = [now, reason]

    if content is not None:
        updates.append("content = ?")
        vals.append(content)
    if status is not None:
        updates.append("status = ?")
        vals.append(status)

    vals.append(thread_id)
    await _connection._exec_write(
        f"UPDATE threads SET {', '.join(updates)} WHERE id = ?",
        tuple(vals)
    )


async def get_dormant_threads(older_than_hours: int = 48) -> list[Thread]:
    """Get active threads untouched for >older_than_hours."""
    conn = await _connection.get_db()
    cutoff = (clock.now_utc() - timedelta(hours=older_than_hours)).isoformat()
    cursor = await conn.execute(
        """SELECT * FROM threads
           WHERE status IN ('open', 'active')
           AND last_touched < ?""",
        (cutoff,)
    )
    rows = await cursor.fetchall()
    return [_row_to_thread(r) for r in rows]


async def archive_stale_threads(older_than_days: int = 7) -> int:
    """Archive dormant threads older than N days. Returns count."""
    cutoff = (clock.now_utc() - timedelta(days=older_than_days)).isoformat()
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """UPDATE threads SET status = 'archived'
           WHERE status = 'dormant' AND last_touched < ?""",
        (cutoff,)
    )
    await conn.commit()
    return cursor.rowcount


async def get_thread_count_by_status() -> dict:
    """Get thread counts by status. For peek command and sleep digest."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT status, COUNT(*) as cnt FROM threads GROUP BY status"
    )
    rows = await cursor.fetchall()
    return {row['status']: row['cnt'] for row in rows}


# ─── Arbiter State ───

async def load_arbiter_state() -> dict:
    """Load arbiter state from DB. Returns dict matching ArbiterState fields."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM arbiter_state WHERE singleton_key = 1"
    )
    row = await cursor.fetchone()
    if not row:
        # Table exists but no row yet — return defaults
        return {
            'consume_count_today': 0,
            'news_engage_count_today': 0,
            'thread_focus_count_today': 0,
            'express_count_today': 0,
            'last_consume_ts': None,
            'last_news_engage_ts': None,
            'last_thread_focus_ts': None,
            'last_express_ts': None,
            'recent_focus_keywords': [],
            'current_date_jst': clock.now().date().isoformat(),
        }

    return {
        'consume_count_today': row['consume_count_today'],
        'news_engage_count_today': row['news_engage_count_today'],
        'thread_focus_count_today': row['thread_focus_count_today'],
        'express_count_today': row['express_count_today'],
        'last_consume_ts': (datetime.fromisoformat(row['last_consume_ts'])
                            if row['last_consume_ts'] else None),
        'last_news_engage_ts': (datetime.fromisoformat(row['last_news_engage_ts'])
                                if row['last_news_engage_ts'] else None),
        'last_thread_focus_ts': (datetime.fromisoformat(row['last_thread_focus_ts'])
                                 if row['last_thread_focus_ts'] else None),
        'last_express_ts': (datetime.fromisoformat(row['last_express_ts'])
                            if row['last_express_ts'] else None),
        'recent_focus_keywords': (json.loads(row['recent_focus_keywords'])
                                  if row['recent_focus_keywords'] else []),
        'current_date_jst': row['current_date_jst'] or '',
    }


async def save_arbiter_state(state: dict):
    """Persist arbiter state to DB."""
    await _connection._exec_write(
        """UPDATE arbiter_state SET
           consume_count_today=?, news_engage_count_today=?,
           thread_focus_count_today=?, express_count_today=?,
           last_consume_ts=?, last_news_engage_ts=?,
           last_thread_focus_ts=?, last_express_ts=?,
           recent_focus_keywords=?, current_date_jst=?
           WHERE singleton_key = 1""",
        (state['consume_count_today'], state['news_engage_count_today'],
         state['thread_focus_count_today'], state['express_count_today'],
         state['last_consume_ts'].isoformat() if state.get('last_consume_ts') else None,
         state['last_news_engage_ts'].isoformat() if state.get('last_news_engage_ts') else None,
         state['last_thread_focus_ts'].isoformat() if state.get('last_thread_focus_ts') else None,
         state['last_express_ts'].isoformat() if state.get('last_express_ts') else None,
         json.dumps(state.get('recent_focus_keywords', [])[:20]),
         state.get('current_date_jst', ''))
    )


# ── Content Pool ──

async def add_to_content_pool(fingerprint: str, source_type: str,
                               source_channel: str, content: str,
                               title: str = '', metadata: dict = None,
                               source_event_id: str = None,
                               tags: list = None,
                               ttl_hours: float = None,
                               salience_base: float = 0.2) -> bool:
    """Insert an item into the content pool. Returns True if inserted (False if dup)."""
    pool_id = str(uuid.uuid4())
    now = clock.now_utc().isoformat()
    try:
        await _connection._exec_write(
            """INSERT INTO content_pool
               (id, fingerprint, source_type, source_channel, content, title,
                metadata, source_event_id, status, salience_base, added_at, tags, ttl_hours)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unseen', ?, ?, ?, ?)
               ON CONFLICT(fingerprint) DO NOTHING""",
            (pool_id, fingerprint, source_type, source_channel, content, title,
             json.dumps(metadata or {}), source_event_id, salience_base, now,
             json.dumps(tags or []), ttl_hours)
        )
        return True
    except Exception:
        return False


async def get_pool_items(status: str = 'unseen', source_types: list = None,
                          limit: int = 20) -> list[dict]:
    """Get content pool items by status and source type."""
    conn = await _connection.get_db()
    if source_types:
        placeholders = ','.join('?' * len(source_types))
        query = f"""SELECT * FROM content_pool
                    WHERE status = ? AND source_type IN ({placeholders})
                    ORDER BY salience_base DESC, added_at ASC
                    LIMIT ?"""
        cursor = await conn.execute(query, (status, *source_types, limit))
    else:
        cursor = await conn.execute(
            """SELECT * FROM content_pool WHERE status = ?
               ORDER BY salience_base DESC, added_at ASC LIMIT ?""",
            (status, limit)
        )
    rows = await cursor.fetchall()
    return [_row_to_pool_item(r) for r in rows]


async def get_pool_item_by_id(pool_id: str) -> Optional[dict]:
    """Get a single pool item by ID."""
    conn = await _connection.get_db()
    cursor = await conn.execute("SELECT * FROM content_pool WHERE id = ?", (pool_id,))
    row = await cursor.fetchone()
    return _row_to_pool_item(row) if row else None


async def update_pool_item(pool_id: str, **kwargs):
    """Update pool item fields."""
    sets = []
    vals = []
    for key in ('status', 'seen_at', 'engaged_at', 'outcome_detail'):
        if key in kwargs:
            sets.append(f"{key} = ?")
            v = kwargs[key]
            vals.append(v.isoformat() if isinstance(v, datetime) else v)
    if not sets:
        return
    vals.append(pool_id)
    await _connection._exec_write(
        f"UPDATE content_pool SET {', '.join(sets)} WHERE id = ?",
        tuple(vals)
    )


async def get_pool_stats() -> dict:
    """Get count of pool items by status."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT status, COUNT(*) FROM content_pool GROUP BY status"
    )
    rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def expire_pool_items():
    """Remove expired pool items (TTL-based)."""
    await _connection._exec_write(
        """DELETE FROM content_pool
           WHERE ttl_hours IS NOT NULL
           AND status = 'unseen'
           AND julianday('now') - julianday(added_at) > ttl_hours / 24.0"""
    )


async def cap_unseen_pool(max_unseen: int = 50):
    """Remove oldest unseen items when pool exceeds cap."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM content_pool WHERE status = 'unseen'"
    )
    row = await cursor.fetchone()
    count = row[0] if row else 0
    if count > max_unseen:
        excess = count - max_unseen
        await _connection._exec_write(
            """DELETE FROM content_pool WHERE id IN (
                SELECT id FROM content_pool
                WHERE status = 'unseen'
                ORDER BY added_at ASC
                LIMIT ?
            )""",
            (excess,)
        )


async def get_unseen_news(min_salience: float = 0.3, limit: int = 5) -> list[dict]:
    """Get unseen news/headline items above salience threshold."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM content_pool
           WHERE status = 'unseen'
           AND source_type = 'rss_headline'
           AND salience_base >= ?
           ORDER BY salience_base DESC, added_at ASC
           LIMIT ?""",
        (min_salience, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_pool_item(r) for r in rows]


def _row_to_pool_item(row) -> dict:
    """Convert a pool row to a dict."""
    d = dict(row)
    for json_key in ('metadata', 'tags'):
        if json_key in d and isinstance(d[json_key], str):
            try:
                d[json_key] = json.loads(d[json_key])
            except (json.JSONDecodeError, TypeError):
                d[json_key] = {} if json_key == 'metadata' else []
    return d
