"""db.state — Room, drives, and engagement state CRUD."""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

import clock
from models.state import (
    RoomState, DrivesState, EngagementState,
    EpistemicCuriosity, EPISTEMIC_CONFIG,
)
import db.connection as _connection


# ─── Room State ───

async def get_room_state() -> RoomState:
    db = await _connection.get_db()
    cursor = await db.execute("SELECT * FROM room_state WHERE id = 1")
    row = await cursor.fetchone()
    return RoomState(
        time_of_day=row['time_of_day'],
        weather=row['weather'],
        shop_status=row['shop_status'],
        ambient_music=row['ambient_music'],
        room_arrangement=json.loads(row['room_arrangement']) if row['room_arrangement'] else {},
        updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
    )


async def update_room_state(**kwargs):
    if not kwargs:
        return
    kwargs['updated_at'] = clock.now_utc().isoformat()
    if 'room_arrangement' in kwargs:
        kwargs['room_arrangement'] = json.dumps(kwargs['room_arrangement'])
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    await _connection._exec_write(f"UPDATE room_state SET {sets} WHERE id = 1", tuple(vals))


# ─── Drives State ───

async def get_drives_state() -> DrivesState:
    db = await _connection.get_db()
    cursor = await db.execute("SELECT * FROM drives_state WHERE id = 1")
    row = await cursor.fetchone()
    # TASK-043: Read diversive_curiosity if available, fall back to curiosity.
    # The DrivesState field is 'curiosity' (for constructor compat), but
    # diversive_curiosity property aliases it for new code.
    row_keys = row.keys() if hasattr(row, 'keys') else []
    if 'diversive_curiosity' in row_keys and row['diversive_curiosity'] is not None:
        curiosity_val = row['diversive_curiosity']
    else:
        curiosity_val = row['curiosity']
    return DrivesState(
        social_hunger=row['social_hunger'],
        curiosity=curiosity_val,
        expression_need=row['expression_need'],
        rest_need=row['rest_need'],
        energy=row['energy'],
        mood_valence=row['mood_valence'],
        mood_arousal=row['mood_arousal'],
        updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
    )


async def save_drives_state(d: DrivesState):
    # TASK-043: Write both curiosity and diversive_curiosity columns for compat
    await _connection._exec_write(
        """UPDATE drives_state SET
           social_hunger=?, curiosity=?, diversive_curiosity=?,
           expression_need=?, rest_need=?,
           energy=?, mood_valence=?, mood_arousal=?, updated_at=?
           WHERE id = 1""",
        (d.social_hunger, d.curiosity, d.curiosity,
         d.expression_need, d.rest_need,
         d.energy, d.mood_valence, d.mood_arousal,
         clock.now_utc().isoformat())
    )


# ─── Engagement State ───

async def get_engagement_state() -> EngagementState:
    db = await _connection.get_db()
    cursor = await db.execute("SELECT * FROM engagement_state WHERE id = 1")
    row = await cursor.fetchone()
    return EngagementState(
        status=row['status'],
        visitor_id=row['visitor_id'],
        context_id=row['context_id'],
        started_at=datetime.fromisoformat(row['started_at']) if row['started_at'] else None,
        last_activity=datetime.fromisoformat(row['last_activity']) if row['last_activity'] else None,
        turn_count=row['turn_count'],
    )


async def update_engagement_state(**kwargs):
    if not kwargs:
        return
    for k in ('started_at', 'last_activity'):
        if k in kwargs and isinstance(kwargs[k], datetime):
            kwargs[k] = kwargs[k].isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    await _connection._exec_write(f"UPDATE engagement_state SET {sets} WHERE id = 1", tuple(vals))


# ─── Settings (key-value store) ───

from typing import Optional


async def get_setting(key: str) -> Optional[str]:
    """Get a setting value by key. Returns None if not found."""
    db = await _connection.get_db()
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row['value'] if row else None


async def set_setting(key: str, value: str):
    """Upsert a setting value."""
    await _connection._exec_write(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, clock.now_utc().isoformat())
    )


# ─── Epistemic Curiosities (TASK-043) ───

def _row_to_ec(row) -> EpistemicCuriosity:
    return EpistemicCuriosity(
        id=row['id'],
        topic=row['topic'],
        question=row['question'],
        intensity=row['intensity'],
        source_type=row['source_type'],
        source_id=row['source_id'],
        created_at=row['created_at'],
        last_reinforced_at=row['last_reinforced_at'],
        decay_rate_per_hour=row['decay_rate'],
        resolved=bool(row['resolved']),
        resolution_source=row['resolution_source'],
    )


async def get_active_epistemic_curiosities(limit: int = 5) -> list[EpistemicCuriosity]:
    """Get active (unresolved) epistemic curiosities, ordered by intensity."""
    conn = await _connection.get_db()
    try:
        cursor = await conn.execute(
            """SELECT * FROM epistemic_curiosities
               WHERE resolved = 0
               ORDER BY intensity DESC
               LIMIT ?""",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [_row_to_ec(r) for r in rows]
    except Exception:
        return []  # table may not exist yet


async def upsert_epistemic_curiosity(ec: EpistemicCuriosity):
    """Insert or update an epistemic curiosity."""
    now_iso = clock.now_utc().isoformat()
    if not ec.id:
        ec.id = str(uuid.uuid4())
    if not ec.created_at:
        ec.created_at = now_iso
    if not ec.last_reinforced_at:
        ec.last_reinforced_at = now_iso

    await _connection._exec_write(
        """INSERT INTO epistemic_curiosities
           (id, topic, question, intensity, source_type, source_id,
            created_at, last_reinforced_at, decay_rate, resolved, resolution_source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             topic = excluded.topic,
             question = excluded.question,
             intensity = excluded.intensity,
             last_reinforced_at = excluded.last_reinforced_at,
             decay_rate = excluded.decay_rate,
             resolved = excluded.resolved,
             resolution_source = excluded.resolution_source""",
        (ec.id, ec.topic, ec.question, ec.intensity,
         ec.source_type, ec.source_id, ec.created_at, ec.last_reinforced_at,
         ec.decay_rate_per_hour, int(ec.resolved), ec.resolution_source)
    )


async def resolve_epistemic_curiosity(ec_id: str, resolution_source: str):
    """Mark an EC as resolved."""
    await _connection._exec_write(
        """UPDATE epistemic_curiosities
           SET resolved = 1, resolution_source = ?
           WHERE id = ?""",
        (resolution_source, ec_id)
    )


async def decay_epistemic_curiosities(elapsed_hours: float) -> list[EpistemicCuriosity]:
    """Decay all active ECs by elapsed_hours. Returns expired ones (intensity < 0.05)."""
    conn = await _connection.get_db()
    try:
        cursor = await conn.execute(
            "SELECT * FROM epistemic_curiosities WHERE resolved = 0"
        )
        rows = await cursor.fetchall()
    except Exception:
        return []

    expired = []
    for row in rows:
        ec = _row_to_ec(row)
        new_intensity = ec.intensity - ec.decay_rate_per_hour * elapsed_hours
        if new_intensity < 0.05:
            # Expire this EC
            ec.intensity = 0.0
            ec.resolved = True
            ec.resolution_source = 'decayed'
            expired.append(ec)
            await _connection._exec_write(
                """UPDATE epistemic_curiosities
                   SET intensity = 0.0, resolved = 1, resolution_source = 'decayed'
                   WHERE id = ?""",
                (ec.id,)
            )
        else:
            await _connection._exec_write(
                "UPDATE epistemic_curiosities SET intensity = ? WHERE id = ?",
                (new_intensity, ec.id)
            )

    return expired


async def evict_weakest_curiosity() -> Optional[EpistemicCuriosity]:
    """Evict the lowest-intensity active EC. Returns the evicted EC or None."""
    conn = await _connection.get_db()
    try:
        cursor = await conn.execute(
            """SELECT * FROM epistemic_curiosities
               WHERE resolved = 0
               ORDER BY intensity ASC
               LIMIT 1"""
        )
        row = await cursor.fetchone()
    except Exception:
        return None

    if not row:
        return None

    ec = _row_to_ec(row)
    ec.resolved = True
    ec.resolution_source = 'evicted'
    await _connection._exec_write(
        """UPDATE epistemic_curiosities
           SET resolved = 1, resolution_source = 'evicted'
           WHERE id = ?""",
        (ec.id,)
    )
    return ec
