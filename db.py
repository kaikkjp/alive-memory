import aiosqlite
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from models.event import Event
from models.state import (
    RoomState, DrivesState, EngagementState, Visitor, VisitorTrait,
    Totem, CollectionItem, JournalEntry, DailySummary,
)

# The shopkeeper lives in JST. All "today" boundaries use JST.
JST = timezone(timedelta(hours=9))

DB_PATH = "data/shopkeeper.db"

_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA busy_timeout=5000")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


# ─── Schema ───

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    ts TIMESTAMP NOT NULL,
    payload JSON NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS inbox (
    event_id TEXT PRIMARY KEY REFERENCES events(id),
    priority FLOAT DEFAULT 0.5,
    read_at TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS room_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    time_of_day TEXT NOT NULL DEFAULT 'morning',
    weather TEXT NOT NULL DEFAULT 'clear',
    shop_status TEXT NOT NULL DEFAULT 'open',
    ambient_music TEXT,
    room_arrangement JSON DEFAULT '{}',
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drives_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    social_hunger FLOAT NOT NULL DEFAULT 0.5,
    curiosity FLOAT NOT NULL DEFAULT 0.5,
    expression_need FLOAT NOT NULL DEFAULT 0.3,
    rest_need FLOAT NOT NULL DEFAULT 0.2,
    energy FLOAT NOT NULL DEFAULT 0.8,
    mood_valence FLOAT NOT NULL DEFAULT 0.0,
    mood_arousal FLOAT NOT NULL DEFAULT 0.3,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS engagement_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL DEFAULT 'none',
    visitor_id TEXT,
    context_id TEXT,
    started_at TIMESTAMP,
    last_activity TIMESTAMP,
    turn_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS visitors (
    id TEXT PRIMARY KEY,
    name TEXT,
    trust_level TEXT NOT NULL DEFAULT 'stranger',
    visit_count INTEGER DEFAULT 0,
    first_visit TIMESTAMP,
    last_visit TIMESTAMP,
    summary TEXT,
    emotional_imprint TEXT,
    hands_state TEXT
);

CREATE TABLE IF NOT EXISTS visitor_traits (
    id TEXT PRIMARY KEY,
    visitor_id TEXT NOT NULL REFERENCES visitors(id),
    trait_category TEXT NOT NULL,
    trait_key TEXT NOT NULL,
    trait_value TEXT NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    source_event_id TEXT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    stability FLOAT NOT NULL DEFAULT 0.2,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_traits_lookup
    ON visitor_traits(visitor_id, trait_category, trait_key, observed_at DESC);

CREATE TABLE IF NOT EXISTS totems (
    id TEXT PRIMARY KEY,
    visitor_id TEXT REFERENCES visitors(id),
    entity TEXT NOT NULL,
    weight FLOAT NOT NULL DEFAULT 0.5,
    context TEXT,
    category TEXT,
    first_seen TIMESTAMP,
    last_referenced TIMESTAMP,
    source_event_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_totems_visitor ON totems(visitor_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_totems_entity ON totems(entity);

CREATE TABLE IF NOT EXISTS journal_entries (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    mood TEXT,
    day_alive INTEGER,
    tags JSON,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collection_items (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    description TEXT,
    location TEXT NOT NULL DEFAULT 'shelf',
    origin TEXT NOT NULL,
    gifted_by TEXT REFERENCES visitors(id),
    her_feeling TEXT,
    emotional_tags JSON,
    display_note TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id TEXT PRIMARY KEY,
    day_number INTEGER,
    date DATE,
    journal_entry_id TEXT REFERENCES journal_entries(id),
    summary_bullets JSON,
    emotional_arc TEXT,
    notable_totems JSON,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversation_log (
    id TEXT PRIMARY KEY,
    visitor_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    ts TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_visitor ON conversation_log(visitor_id, ts);

CREATE TABLE IF NOT EXISTS cycle_log (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    drives JSON,
    focus_salience FLOAT,
    focus_type TEXT,
    routing_focus TEXT,
    token_budget INTEGER,
    memory_count INTEGER,
    internal_monologue TEXT,
    dialogue TEXT,
    expression TEXT,
    actions JSON,
    dropped JSON,
    ts TIMESTAMP NOT NULL
);
"""


async def init_db():
    db = await get_db()
    for statement in SCHEMA.split(';'):
        statement = statement.strip()
        if statement:
            await db.execute(statement)
    await db.commit()

    # Ensure singleton rows exist
    await db.execute(
        "INSERT OR IGNORE INTO room_state (id) VALUES (1)"
    )
    await db.execute(
        "INSERT OR IGNORE INTO drives_state (id) VALUES (1)"
    )
    await db.execute(
        "INSERT OR IGNORE INTO engagement_state (id) VALUES (1)"
    )
    await db.commit()


# ─── Event Store ───

async def append_event(event: Event):
    db = await get_db()
    await db.execute(
        "INSERT INTO events (id, event_type, source, ts, payload) VALUES (?, ?, ?, ?, ?)",
        (event.id, event.event_type, event.source, event.ts.isoformat(), json.dumps(event.payload))
    )
    await db.commit()


async def get_events_since(since: datetime, event_type: str = None) -> list[Event]:
    db = await get_db()
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
    db = await get_db()
    today_jst = datetime.now(JST).date().isoformat()
    cursor = await db.execute(
        "SELECT * FROM events WHERE date(ts, '+9 hours') = ? ORDER BY ts",
        (today_jst,)
    )
    rows = await cursor.fetchall()
    return [_row_to_event(r) for r in rows]


def _row_to_event(row) -> Event:
    return Event(
        id=row['id'],
        event_type=row['event_type'],
        source=row['source'],
        ts=datetime.fromisoformat(row['ts']),
        payload=json.loads(row['payload']),
    )


# ─── Inbox ───

async def inbox_add(event_id: str, priority: float = 0.5):
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO inbox (event_id, priority) VALUES (?, ?)",
        (event_id, priority)
    )
    await db.commit()


async def inbox_get_unread() -> list[Event]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT e.* FROM inbox i
           JOIN events e ON i.event_id = e.id
           WHERE i.read_at IS NULL
           ORDER BY i.priority DESC, e.ts ASC"""
    )
    rows = await cursor.fetchall()
    return [_row_to_event(r) for r in rows]


async def inbox_mark_read(event_id: str):
    db = await get_db()
    await db.execute(
        "UPDATE inbox SET read_at = ? WHERE event_id = ?",
        (datetime.now(timezone.utc).isoformat(), event_id)
    )
    await db.commit()


# ─── Room State ───

async def get_room_state() -> RoomState:
    db = await get_db()
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
    db = await get_db()
    kwargs['updated_at'] = datetime.now(timezone.utc).isoformat()
    if 'room_arrangement' in kwargs:
        kwargs['room_arrangement'] = json.dumps(kwargs['room_arrangement'])
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    await db.execute(f"UPDATE room_state SET {sets} WHERE id = 1", vals)
    await db.commit()


# ─── Drives State ───

async def get_drives_state() -> DrivesState:
    db = await get_db()
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
    db = await get_db()
    await db.execute(
        """UPDATE drives_state SET
           social_hunger=?, curiosity=?, expression_need=?, rest_need=?,
           energy=?, mood_valence=?, mood_arousal=?, updated_at=?
           WHERE id = 1""",
        (d.social_hunger, d.curiosity, d.expression_need, d.rest_need,
         d.energy, d.mood_valence, d.mood_arousal,
         datetime.now(timezone.utc).isoformat())
    )
    await db.commit()


# ─── Engagement State ───

async def get_engagement_state() -> EngagementState:
    db = await get_db()
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
    db = await get_db()
    for k in ('started_at', 'last_activity'):
        if k in kwargs and isinstance(kwargs[k], datetime):
            kwargs[k] = kwargs[k].isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    await db.execute(f"UPDATE engagement_state SET {sets} WHERE id = 1", vals)
    await db.commit()


# ─── Visitors ───

async def get_visitor(visitor_id: str) -> Optional[Visitor]:
    db = await get_db()
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
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT OR IGNORE INTO visitors (id, visit_count, first_visit, last_visit) VALUES (?, 1, ?, ?)",
        (visitor_id, now, now)
    )
    await db.commit()
    return await get_visitor(visitor_id)


async def update_visitor(visitor_id: str, **kwargs):
    if not kwargs:
        return
    db = await get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [visitor_id]
    await db.execute(f"UPDATE visitors SET {sets} WHERE id = ?", vals)
    await db.commit()


async def increment_visit(visitor_id: str):
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE visitors SET visit_count = visit_count + 1, last_visit = ? WHERE id = ?",
        (now, visitor_id)
    )
    await db.commit()
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
    db = await get_db()
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
    db = await get_db()
    await db.execute(
        """INSERT INTO visitor_traits
           (id, visitor_id, trait_category, trait_key, trait_value, observed_at, source_event_id, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), visitor_id, trait_category, trait_key, trait_value,
         datetime.now(timezone.utc).isoformat(), source_event_id, confidence)
    )
    await db.commit()


async def get_visitor_traits(visitor_id: str, limit: int = 20) -> list[VisitorTrait]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM visitor_traits
           WHERE visitor_id = ? AND status = 'active'
           ORDER BY observed_at DESC LIMIT ?""",
        (visitor_id, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_trait(r) for r in rows]


async def get_all_active_traits() -> list[VisitorTrait]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM visitor_traits WHERE status IN ('active', 'anomaly')"
    )
    rows = await cursor.fetchall()
    return [_row_to_trait(r) for r in rows]


async def get_trait_history(visitor_id: str, category: str, key: str) -> list[VisitorTrait]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM visitor_traits
           WHERE visitor_id = ? AND trait_category = ? AND trait_key = ?
           ORDER BY observed_at DESC""",
        (visitor_id, category, key)
    )
    rows = await cursor.fetchall()
    return [_row_to_trait(r) for r in rows]


async def update_trait_stability(trait_id: str, stability: float):
    db = await get_db()
    await db.execute("UPDATE visitor_traits SET stability = ? WHERE id = ?", (stability, trait_id))
    await db.commit()


async def update_trait_status(trait_id: str, status: str):
    db = await get_db()
    await db.execute("UPDATE visitor_traits SET status = ? WHERE id = ?", (status, trait_id))
    await db.commit()


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
    db = await get_db()
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
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO totems
           (id, visitor_id, entity, weight, context, category, first_seen, last_referenced, source_event_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), visitor_id, entity, weight, context, category, now, now, source_event_id)
    )
    await db.commit()


async def update_totem(entity: str, visitor_id: str = None,
                       weight: float = None, last_referenced: datetime = None):
    db = await get_db()
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
        await db.execute(f"UPDATE totems SET {', '.join(updates)} {where}", vals)
        await db.commit()


def _row_to_totem(row) -> Totem:
    return Totem(
        id=row['id'], entity=row['entity'], weight=row['weight'],
        visitor_id=row['visitor_id'], context=row['context'],
        category=row['category'],
        first_seen=datetime.fromisoformat(row['first_seen']) if row['first_seen'] else None,
        last_referenced=datetime.fromisoformat(row['last_referenced']) if row['last_referenced'] else None,
        source_event_id=row['source_event_id'],
    )


# ─── Collection Items ───

async def insert_collection_item(item: dict):
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
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
    await db.commit()


async def search_collection(query: str = '', limit: int = 3) -> list[CollectionItem]:
    db = await get_db()
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


# ─── Journal ───

async def insert_journal(content: str, mood: str = None, tags: list = None,
                         day_alive: int = None) -> str:
    db = await get_db()
    jid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO journal_entries (id, content, mood, day_alive, tags, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (jid, content, mood, day_alive, json.dumps(tags or []), now)
    )
    await db.commit()
    return jid


async def get_recent_journal(limit: int = 2) -> list[JournalEntry]:
    db = await get_db()
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


# ─── Daily Summary ───

async def insert_daily_summary(summary: dict):
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO daily_summaries
           (id, day_number, date, journal_entry_id, summary_bullets, emotional_arc, notable_totems, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), summary.get('day_number'), summary.get('date'),
         summary.get('journal_entry_id'), json.dumps(summary.get('summary_bullets', [])),
         summary.get('emotional_arc'), json.dumps(summary.get('notable_totems', [])), now)
    )
    await db.commit()


# ─── Conversation Log ───

async def append_conversation(visitor_id: str, role: str, text: str):
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO conversation_log (id, visitor_id, role, text, ts) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), visitor_id, role, text, now)
    )
    await db.commit()


async def get_recent_conversation(visitor_id: str, limit: int = 10) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT role, text FROM conversation_log WHERE visitor_id = ? ORDER BY ts DESC LIMIT ?",
        (visitor_id, limit)
    )
    rows = await cursor.fetchall()
    return [{'role': r['role'], 'text': r['text']} for r in reversed(rows)]


# ─── Cycle Log ───

async def log_cycle(log: dict):
    db = await get_db()
    await db.execute(
        """INSERT INTO cycle_log
           (id, mode, drives, focus_salience, focus_type, routing_focus,
            token_budget, memory_count, internal_monologue, dialogue,
            expression, actions, dropped, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (log['id'], log['mode'], json.dumps(log.get('drives', {})),
         log.get('focus_salience'), log.get('focus_type'),
         log.get('routing_focus'), log.get('token_budget'),
         log.get('memory_count'), log.get('internal_monologue'),
         log.get('dialogue'), log.get('expression'),
         json.dumps(log.get('actions', [])), json.dumps(log.get('dropped', [])),
         datetime.now(timezone.utc).isoformat())
    )
    await db.commit()


# ─── Self Knowledge ───

async def get_self_discoveries() -> str:
    db = await get_db()
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
    db = await get_db()
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
    db = await get_db()
    today_jst = datetime.now(JST).date().isoformat()
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM cycle_log WHERE date(ts, '+9 hours') = ? AND token_budget >= 10000",
        (today_jst,)
    )
    row = await cursor.fetchone()
    return row['cnt'] if row else 0
