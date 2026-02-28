"""db.events — Event store and inbox operations."""

import json
from datetime import datetime

import clock
from models.event import Event
import db.connection as _connection


# ─── Event Store ───

async def append_event(event: Event):
    await _connection._exec_write(
        """INSERT INTO events (id, event_type, source, ts, payload,
           channel, salience_base, salience_dynamic, ttl_hours, engaged_at, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event.id, event.event_type, event.source, event.ts.isoformat(),
         json.dumps(event.payload),
         event.channel, event.salience_base, event.salience_dynamic,
         event.ttl_hours,
         event.engaged_at.isoformat() if event.engaged_at else None,
         event.outcome)
    )


async def get_events_since(since: datetime, event_type: str = None) -> list[Event]:
    db = await _connection.get_db()
    if event_type:
        cursor = await db.execute(
            "SELECT * FROM events WHERE ts > ? AND event_type = ? ORDER BY ts",
            (since.isoformat(), event_type)
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM events WHERE ts > ? ORDER BY ts",
            (since.isoformat(),)
        )
    rows = await cursor.fetchall()
    return [_row_to_event(r) for r in rows]


async def get_events_today() -> list[Event]:
    db = await _connection.get_db()
    today_jst = clock.now().date().isoformat()
    cursor = await db.execute(
        "SELECT * FROM events WHERE date(ts, '+9 hours') = ? ORDER BY ts",
        (today_jst,)
    )
    rows = await cursor.fetchall()
    return [_row_to_event(r) for r in rows]


def _row_to_event(row) -> Event:
    # Safe access for Living Loop columns (may be missing on pre-migration DBs)
    def _col(name, default=None):
        try:
            return row[name]
        except (IndexError, KeyError):
            return default

    return Event(
        id=row['id'],
        event_type=row['event_type'],
        source=row['source'],
        ts=datetime.fromisoformat(row['ts']),
        payload=json.loads(row['payload']),
        channel=_col('channel', 'system') or 'system',
        salience_base=_col('salience_base', 0.5) or 0.5,
        salience_dynamic=_col('salience_dynamic', 0.0) or 0.0,
        ttl_hours=_col('ttl_hours'),
        engaged_at=(datetime.fromisoformat(_col('engaged_at'))
                    if _col('engaged_at') else None),
        outcome=_col('outcome'),
    )


# ─── Inbox ───

async def inbox_add(event_id: str, priority: float = 0.5):
    await _connection._exec_write(
        "INSERT OR IGNORE INTO inbox (event_id, priority) VALUES (?, ?)",
        (event_id, priority)
    )


async def inbox_get_unread() -> list[Event]:
    db = await _connection.get_db()
    cursor = await db.execute(
        """SELECT e.* FROM inbox i
           JOIN events e ON i.event_id = e.id
           WHERE i.read_at IS NULL
           AND (e.ttl_hours IS NULL
                OR (julianday('now') - julianday(e.ts)) < e.ttl_hours / 24.0)
           ORDER BY i.priority DESC, e.ts ASC"""
    )
    rows = await cursor.fetchall()
    return [_row_to_event(r) for r in rows]


async def inbox_flush_stale_visitor_events():
    """Mark all unread visitor events as read.

    Called on visitor_connect to prevent stale disconnect/speech events
    from a previous session leaking into the new session's perceptions.
    """
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        """UPDATE inbox SET read_at = ?
           WHERE read_at IS NULL
           AND event_id IN (
               SELECT e.id FROM events e
               JOIN inbox i ON i.event_id = e.id
               WHERE i.read_at IS NULL
               AND e.event_type IN (
                   'visitor_connect', 'visitor_disconnect',
                   'visitor_speech', 'visitor_silence'
               )
           )""",
        (now,)
    )


async def inbox_mark_read(event_id: str):
    await _connection._exec_write(
        "UPDATE inbox SET read_at = ? WHERE event_id = ?",
        (clock.now_utc().isoformat(), event_id)
    )


# ─── Peek Queries ───

async def get_recent_events(limit: int = 20) -> list[Event]:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    return list(reversed([_row_to_event(r) for r in rows]))


async def update_event_outcome(event_id: str, outcome: str,
                                engaged_at: datetime = None) -> None:
    """Update an event's outcome and engaged_at timestamp.

    Used by executor to couple pool status changes with their source events.
    """
    ts = (engaged_at or clock.now_utc()).isoformat()
    await _connection._exec_write(
        "UPDATE events SET outcome = ?, engaged_at = ? WHERE id = ?",
        (outcome, ts, event_id)
    )
