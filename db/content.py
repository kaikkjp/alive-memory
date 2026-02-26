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


async def get_open_threads() -> list[Thread]:
    """Get all open/active threads (no limit). For dedup checks."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM threads
           WHERE status IN ('open', 'active')
           ORDER BY last_touched DESC"""
    )
    rows = await cursor.fetchall()
    return [_row_to_thread(r) for r in rows]


async def append_to_thread(thread_id: str, content: str):
    """Append content to an existing thread's content field."""
    conn = await _connection.get_db()
    now = clock.now_utc().isoformat()
    cursor = await conn.execute(
        "SELECT content FROM threads WHERE id = ?", (thread_id,)
    )
    row = await cursor.fetchone()
    if row:
        existing = row['content'] or ''
        new_content = f"{existing}\n{content}".strip() if existing else content
        await _connection._exec_write(
            """UPDATE threads SET content = ?, last_touched = ?,
               touch_count = touch_count + 1, touch_reason = 'dedup_merge'
               WHERE id = ?""",
            (new_content, now, thread_id)
        )


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
    for key in ('status', 'seen_at', 'engaged_at', 'outcome_detail',
                'enriched_text', 'content_type', 'saved_by_cortex', 'saved_at',
                'title_embedding', 'consumed', 'consumed_at', 'consumption_output'):
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
    """Remove oldest unseen items when pool exceeds cap.

    Curated items (source_channel='file') are exempt from eviction.
    """
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
                AND source_channel != 'file'
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


async def get_content_pool_dashboard() -> dict:
    """Get content pool overview for the dashboard panel.

    Returns dict with:
    - total: int — count of unconsumed (unseen) items
    - by_type: list[dict] — [{source_type, count}] breakdown
    - recent: list[dict] — last 5 added items [{title, source_type, added_at}]
    - oldest_age_hours: float|None — hours since oldest unseen item was added
    """
    conn = await _connection.get_db()

    # Total unseen
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM content_pool WHERE status = 'unseen'"
    )
    row = await cursor.fetchone()
    total = row[0] if row else 0

    # Breakdown by source_type
    cursor = await conn.execute(
        """SELECT source_type, COUNT(*) as cnt FROM content_pool
           WHERE status = 'unseen'
           GROUP BY source_type ORDER BY cnt DESC"""
    )
    rows = await cursor.fetchall()
    by_type = [{'source_type': r[0], 'count': r[1]} for r in rows]

    # Last 5 recently added (any status — shows recent arrivals)
    cursor = await conn.execute(
        """SELECT title, source_type, added_at FROM content_pool
           ORDER BY added_at DESC LIMIT 5"""
    )
    rows = await cursor.fetchall()
    recent = [{'title': r[0] or '(untitled)', 'source_type': r[1],
               'added_at': r[2]} for r in rows]

    # Age of oldest unseen item
    cursor = await conn.execute(
        """SELECT MIN(added_at) FROM content_pool
           WHERE status = 'unseen'"""
    )
    row = await cursor.fetchone()
    oldest_age_hours = None
    if row and row[0]:
        oldest_ts = datetime.fromisoformat(row[0])
        if oldest_ts.tzinfo is None:
            oldest_ts = oldest_ts.replace(tzinfo=timezone.utc)
        delta = clock.now_utc() - oldest_ts
        oldest_age_hours = round(delta.total_seconds() / 3600, 1)

    return {
        'total': total,
        'by_type': by_type,
        'recent': recent,
        'oldest_age_hours': oldest_age_hours,
    }


async def get_feed_pipeline_dashboard() -> dict:
    """Get feed pipeline health overview for the dashboard panel.

    Returns dict with:
    - status: str — 'running' | 'paused' | 'error' (derived from recent ingestion activity)
    - queue_depth: int — count of unseen items waiting for processing
    - last_success_ts: str|None — ISO timestamp of most recent successful ingestion
    - failed_24h: int — count of items that failed in last 24h
    - last_error: str|None — most recent error message (if any failures)
    - rate_24h: int — items ingested in last 24h
    """
    conn = await _connection.get_db()

    # Queue depth: unseen items waiting for processing
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM content_pool WHERE status = 'unseen'"
    )
    row = await cursor.fetchone()
    queue_depth = row[0] if row else 0

    # Last successful ingestion: most recently added item
    cursor = await conn.execute(
        "SELECT MAX(added_at) FROM content_pool"
    )
    row = await cursor.fetchone()
    last_success_ts = row[0] if row and row[0] else None

    # Items added in last 24h (ingestion rate)
    cutoff_24h = (clock.now_utc() - timedelta(hours=24)).isoformat()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM content_pool WHERE added_at >= ?",
        (cutoff_24h,)
    )
    row = await cursor.fetchone()
    rate_24h = row[0] if row else 0

    # Failed items in last 24h
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM content_pool WHERE status = 'failed' AND added_at >= ?",
        (cutoff_24h,)
    )
    row = await cursor.fetchone()
    failed_24h = row[0] if row else 0

    # Last error message from failed items
    last_error = None
    if failed_24h > 0:
        cursor = await conn.execute(
            """SELECT metadata FROM content_pool
               WHERE status = 'failed' AND added_at >= ?
               ORDER BY added_at DESC LIMIT 1""",
            (cutoff_24h,)
        )
        row = await cursor.fetchone()
        if row and row[0]:
            try:
                meta = json.loads(row[0])
                last_error = meta.get('error', None)
            except (json.JSONDecodeError, TypeError):
                pass

    # Derive pipeline status from activity patterns
    # If items were added in last 2h → running
    # If items exist but none in last 2h → paused
    # If failures in last 24h → error
    if failed_24h > 0:
        status = 'error'
    elif last_success_ts:
        try:
            last_ts = datetime.fromisoformat(last_success_ts)
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            hours_since = (clock.now_utc() - last_ts).total_seconds() / 3600
            status = 'running' if hours_since < 2 else 'paused'
        except (ValueError, TypeError):
            status = 'paused'
    else:
        status = 'paused'

    return {
        'status': status,
        'queue_depth': queue_depth,
        'last_success_ts': last_success_ts,
        'failed_24h': failed_24h,
        'last_error': last_error,
        'rate_24h': rate_24h,
    }


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


# ── Consumption History (TASK-028) ──

_STATUS_TO_OUTCOMES: dict[str, list[str]] = {
    'accepted': ['collection'],
    'reflected': ['memory'],
    'engaged': ['thread'],
    'seen': ['no output'],
}


async def get_consumption_history(limit: int = 20) -> list[dict]:
    """Get recently consumed content pool items with outcome tags.

    Returns list of dicts sorted by consumption time (most recent first):
        {
            'id': str,
            'title': str,
            'source_type': str,
            'consumed_at': str (ISO timestamp),
            'outcomes': list[str]  — e.g. ['memory'], ['collection', 'thread'], ['no output']
        }
    """
    conn = await _connection.get_db()

    # Items that were consumed (any status beyond 'unseen' and 'failed')
    cursor = await conn.execute(
        """SELECT id, title, source_type, status,
                  seen_at, engaged_at, outcome_detail
           FROM content_pool
           WHERE status NOT IN ('unseen', 'failed')
           ORDER BY COALESCE(engaged_at, seen_at) DESC
           LIMIT ?""",
        (limit,)
    )
    rows = await cursor.fetchall()

    # Collect pool IDs to batch-check for thread creation
    pool_ids = [r['id'] for r in rows]
    thread_pool_ids: set[str] = set()
    if pool_ids:
        # Check if any threads reference these pool items via source_event_id
        placeholders = ','.join('?' * len(pool_ids))
        # Pool items link to events via source_event_id, threads link to events too
        cursor = await conn.execute(
            f"""SELECT DISTINCT cp.id
                FROM content_pool cp
                JOIN threads t ON t.source_event_id = cp.source_event_id
                WHERE cp.id IN ({placeholders})
                  AND cp.source_event_id IS NOT NULL""",
            pool_ids,
        )
        thread_rows = await cursor.fetchall()
        thread_pool_ids = {r[0] for r in thread_rows}

    result = []
    for row in rows:
        status = row['status']
        outcomes = list(_STATUS_TO_OUTCOMES.get(status, ['no output']))

        # Enrich: if a thread was created from this item, add 'thread'
        if row['id'] in thread_pool_ids and 'thread' not in outcomes:
            outcomes.append('thread')

        # If outcome_detail is set, it may override or supplement
        if row['outcome_detail'] and 'no output' in outcomes:
            outcomes.remove('no output')
            outcomes.append('memory')

        consumed_at = row['engaged_at'] or row['seen_at']

        result.append({
            'id': row['id'],
            'title': (row['title'] or '(untitled)')[:80],
            'source_type': row['source_type'] or 'unknown',
            'consumed_at': consumed_at,
            'outcomes': outcomes,
        })

    return result


# ── Cross-channel dedup ──

async def url_exists_in_pool(canonical_url: str) -> bool:
    """Check if a URL already exists in the pool from any channel."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT 1 FROM content_pool WHERE content = ? LIMIT 1",
        (canonical_url,)
    )
    return await cursor.fetchone() is not None


# ── Enrichment helpers (TASK-034) ──

async def get_enriched_text_for_url(url: str) -> Optional[str]:
    """Check if a URL has already been enriched. Returns enriched_text or None."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT enriched_text FROM content_pool
           WHERE content = ? AND enriched_text IS NOT NULL
           LIMIT 1""",
        (url,)
    )
    row = await cursor.fetchone()
    return row['enriched_text'] if row else None


# ── Notification layer (TASK-041) ──

async def get_notification_candidates(max_items: int = 5,
                                       cooldown_minutes: int = 10) -> list[dict]:
    """Get unseen content pool items eligible for notification surfacing.

    Returns items not surfaced within cooldown_minutes, ordered by a scoring
    formula that balances recency, source diversity, and unseen status.
    Saved items get priority boost and skip cooldown.
    """
    conn = await _connection.get_db()
    now_iso = clock.now_utc().isoformat()
    cutoff_iso = (clock.now_utc() - timedelta(minutes=cooldown_minutes)).isoformat()

    # Get saved items first (skip cooldown, priority boost)
    cursor = await conn.execute(
        """SELECT * FROM content_pool
           WHERE status = 'unseen' AND saved_by_cortex = 1
           ORDER BY saved_at DESC
           LIMIT ?""",
        (max_items,)
    )
    saved_rows = await cursor.fetchall()
    saved_items = [_row_to_pool_item(r) for r in saved_rows]
    saved_ids = {item['id'] for item in saved_items}

    remaining = max_items - len(saved_items)
    if remaining <= 0:
        return saved_items[:max_items]

    # Get non-saved unseen items, excluding those on cooldown
    # Use a subquery to check notification_log for cooldown
    cursor = await conn.execute(
        """SELECT cp.* FROM content_pool cp
           WHERE cp.status = 'unseen'
           AND (cp.saved_by_cortex IS NULL OR cp.saved_by_cortex = 0)
           AND cp.id NOT IN (
               SELECT nl.content_id FROM notification_log nl
               WHERE nl.surfaced_at >= ?
           )
           ORDER BY cp.added_at DESC
           LIMIT ?""",
        (cutoff_iso, remaining * 3)  # fetch extra for source diversity filtering
    )
    rows = await cursor.fetchall()
    candidates = [_row_to_pool_item(r) for r in rows
                  if r['id'] not in saved_ids]

    # Apply source diversity: don't take more than 2 from the same source_channel
    source_counts: dict[str, int] = {}
    diverse_candidates = []
    for item in candidates:
        channel = item.get('source_channel', 'unknown')
        if source_counts.get(channel, 0) < 2:
            diverse_candidates.append(item)
            source_counts[channel] = source_counts.get(channel, 0) + 1
        if len(diverse_candidates) >= remaining:
            break

    return saved_items + diverse_candidates


async def log_notification_surfaced(content_id: str, cycle_id: str = None):
    """Record that a content item was surfaced as a notification."""
    now_iso = clock.now_utc().isoformat()
    await _connection._exec_write(
        "INSERT INTO notification_log (content_id, surfaced_at, cycle_id) VALUES (?, ?, ?)",
        (content_id, now_iso, cycle_id)
    )


async def save_content_for_later(pool_id: str):
    """Mark a content pool item as saved by cortex for later reading."""
    now_iso = clock.now_utc().isoformat()
    await _connection._exec_write(
        "UPDATE content_pool SET saved_by_cortex = 1, saved_at = ? WHERE id = ?",
        (now_iso, pool_id)
    )


# ── Agent Feeds ──

async def get_agent_feeds() -> list[dict]:
    """Get all configured agent RSS feeds."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM agent_feeds ORDER BY created_at DESC"
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def create_agent_feed(url: str, label: str = None,
                             poll_interval: int = 60) -> int:
    """Create a new agent RSS feed. Returns the new feed ID."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """INSERT INTO agent_feeds (url, label, poll_interval_minutes)
           VALUES (?, ?, ?)""",
        (url, label, poll_interval)
    )
    await conn.commit()
    return cursor.lastrowid


async def update_agent_feed(feed_id: int, **kwargs) -> int:
    """Update an agent feed. Returns number of rows changed."""
    if not kwargs:
        return 0
    sets = ', '.join(f'{k} = ?' for k in kwargs)
    values = list(kwargs.values()) + [feed_id]
    sql = f"UPDATE agent_feeds SET {sets} WHERE id = ?"
    params = tuple(values)
    conn = await _connection.get_db()
    if _connection._tx_depth.get() > 0:
        cursor = await conn.execute(sql, params)
    else:
        async with _connection._write_lock:
            cursor = await conn.execute(sql, params)
            await conn.commit()
    return cursor.rowcount


async def delete_agent_feed(feed_id: int) -> bool:
    """Delete an agent feed. Returns True if deleted."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "DELETE FROM agent_feeds WHERE id = ?",
        (feed_id,)
    )
    await conn.commit()
    return cursor.rowcount > 0


# ── Manager Drops ──

async def get_manager_drops(limit: int = 50) -> list[dict]:
    """Get content pool items dropped by the manager, with consumption status."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, title, content, source_type, status,
                  added_at, consumed_at, consumption_output
           FROM content_pool
           WHERE source_channel = 'manager'
           ORDER BY added_at DESC
           LIMIT ?""",
        (limit,)
    )
    rows = await cursor.fetchall()
    return [
        {
            'id': row['id'],
            'title': row['title'],
            'content': row['content'],
            'source_type': row['source_type'],
            'status': row['status'],
            'added_at': row['added_at'],
            'consumed_at': row['consumed_at'],
            'consumption_output': row['consumption_output'],
        }
        for row in rows
    ]


async def expire_saved_items(max_age_hours: float = 48.0):
    """Remove saved status from items saved more than max_age_hours ago."""
    cutoff = (clock.now_utc() - timedelta(hours=max_age_hours)).isoformat()
    await _connection._exec_write(
        """UPDATE content_pool
           SET saved_by_cortex = 0, saved_at = NULL
           WHERE saved_by_cortex = 1 AND saved_at < ?""",
        (cutoff,)
    )
