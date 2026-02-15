"""db.state — Room, drives, and engagement state CRUD."""

import json
from datetime import datetime

import clock
from models.state import RoomState, DrivesState, EngagementState
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
    return DrivesState(
        social_hunger=row['social_hunger'],
        curiosity=row['curiosity'],
        expression_need=row['expression_need'],
        rest_need=row['rest_need'],
        energy=row['energy'],
        mood_valence=row['mood_valence'],
        mood_arousal=row['mood_arousal'],
        updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
    )


async def save_drives_state(d: DrivesState):
    await _connection._exec_write(
        """UPDATE drives_state SET
           social_hunger=?, curiosity=?, expression_need=?, rest_need=?,
           energy=?, mood_valence=?, mood_arousal=?, updated_at=?
           WHERE id = 1""",
        (d.social_hunger, d.curiosity, d.expression_need, d.rest_need,
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
