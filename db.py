import asyncio
import aiosqlite
import contextvars
import json
import os
import pathlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from models.event import Event
from models.state import (
    RoomState, DrivesState, EngagementState, Visitor, VisitorTrait,
    Totem, CollectionItem, JournalEntry, DailySummary, Thread,
)

COLD_SEARCH_ENABLED = os.getenv('COLD_SEARCH_ENABLED', 'false').lower() == 'true'

# The shopkeeper lives in JST. All "today" boundaries use JST.
JST = timezone(timedelta(hours=9))

DB_PATH = "data/shopkeeper.db"

_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        # Load sqlite-vec extension for cold memory search (Phase 2)
        if COLD_SEARCH_ENABLED:
            _ext_enabled = False
            try:
                import sqlite_vec
                await _db.enable_load_extension(True)
                _ext_enabled = True
                sqlite_vec.load(_db._conn)  # raw sqlite3.Connection
            except ImportError:
                print("[DB] sqlite-vec not installed — cold search disabled")
            except Exception as e:
                print(f"[DB] Failed to load sqlite-vec: {e}")
            finally:
                if _ext_enabled:
                    try:
                        await _db.enable_load_extension(False)
                    except Exception:
                        pass  # best-effort disable
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA busy_timeout=5000")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


# ─── Write serialization ───
# SQLite transaction state lives on the shared connection.  A write (execute)
# from any coroutine lands inside whatever transaction is active, and a commit
# from any coroutine commits everything.  We use a lock so that:
#   - transaction() holds the lock for its entire lifetime (BEGIN → COMMIT/ROLLBACK)
#   - standalone writes acquire the lock around execute+commit as an atomic unit
# This prevents interleaving: no outside write can land inside a transaction,
# and no outside commit can finalize a transaction early.
_write_lock = asyncio.Lock()

# Task-local depth counter (for nested transaction() calls within one task).
_tx_depth: contextvars.ContextVar[int] = contextvars.ContextVar('_tx_depth', default=0)


async def _exec_write(sql: str, params: tuple = ()):
    """Execute a single write statement with proper serialization.

    Inside a transaction block (same task): executes directly (lock already held).
    Outside a transaction: acquires _write_lock, executes, commits, releases.
    """
    conn = await get_db()
    if _tx_depth.get() > 0:
        # Inside a transaction — lock is already held by this task
        await conn.execute(sql, params)
    else:
        async with _write_lock:
            await conn.execute(sql, params)
            await conn.commit()


class transaction:
    """Async context manager that batches all writes into one atomic commit.

    Usage:
        async with db.transaction():
            await db.append_event(...)
            await db.log_cycle(...)
        # single COMMIT happens here; ROLLBACK on exception

    Holds _write_lock for the entire lifetime so no other coroutine can
    execute writes or commits on the shared connection while this
    transaction is open.
    """

    async def __aenter__(self):
        depth = _tx_depth.get()
        if depth == 0:
            await _write_lock.acquire()
            try:
                conn = await get_db()
                await conn.execute("BEGIN IMMEDIATE")
            except BaseException:
                _write_lock.release()
                raise
        _tx_depth.set(depth + 1)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        depth = _tx_depth.get() - 1
        _tx_depth.set(depth)
        if depth == 0:
            try:
                conn = await get_db()
                if exc_type is None:
                    await conn.commit()
                else:
                    await conn.rollback()
            finally:
                _write_lock.release()
        return False  # don't suppress exception


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
    body_state TEXT,
    gaze TEXT,
    actions JSON,
    dropped JSON,
    next_cycle_hints JSON,
    ts TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS day_memory (
    id TEXT PRIMARY KEY,
    ts TIMESTAMP NOT NULL,
    salience FLOAT NOT NULL,
    moment_type TEXT NOT NULL,
    visitor_id TEXT,
    summary TEXT NOT NULL,
    raw_refs JSON,
    tags JSON,
    retry_count INTEGER DEFAULT 0,
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_day_memory_salience ON day_memory(salience DESC);
CREATE INDEX IF NOT EXISTS idx_day_memory_visitor ON day_memory(visitor_id);
CREATE INDEX IF NOT EXISTS idx_day_memory_unprocessed ON day_memory(processed_at) WHERE processed_at IS NULL;
"""


async def add_column_if_missing(conn, table: str, column: str,
                                col_type: str, default=None):
    """Add a column to a table if it doesn't already exist.

    SQLite lacks ADD COLUMN IF NOT EXISTS, so we check PRAGMA table_info.
    """
    cursor = await conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in await cursor.fetchall()}
    if column not in existing:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}"
        )


async def run_migrations(conn):
    """Apply unapplied migrations in order. Safe to call on every startup."""
    # Ensure schema_version table
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            filename TEXT NOT NULL
        )""")
    await conn.commit()

    # Get max applied version
    cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    max_version = row[0] or 0

    # Scan migrations/ directory
    migrations_dir = pathlib.Path(__file__).parent / 'migrations'
    if not migrations_dir.exists():
        return

    sql_files = sorted(migrations_dir.glob('*.sql'))
    for f in sql_files:
        version = int(f.name.split('_')[0])
        if version <= max_version:
            continue

        # Special handling for migration 002: event contract columns
        if version == 2:
            await _apply_event_contract_migration(conn)
        else:
            sql = f.read_text()
            # Execute statements individually (executescript not available in aiosqlite)
            for stmt in sql.split(';'):
                # Strip comment-only lines before checking emptiness —
                # a segment like "-- comment\nCREATE TABLE..." must not be
                # skipped just because the first line is a comment.
                lines = stmt.strip().splitlines()
                cleaned = '\n'.join(
                    line for line in lines
                    if not line.strip().startswith('--')
                ).strip()
                if cleaned:
                    await conn.execute(cleaned)

        await conn.execute(
            "INSERT INTO schema_version (version, filename) VALUES (?, ?)",
            (version, f.name)
        )
        await conn.commit()


async def _apply_event_contract_migration(conn):
    """Add Living Loop columns to events table."""
    await add_column_if_missing(conn, 'events', 'channel', 'TEXT', "'system'")
    await add_column_if_missing(conn, 'events', 'salience_base', 'FLOAT', '0.5')
    await add_column_if_missing(conn, 'events', 'salience_dynamic', 'FLOAT', '0.0')
    await add_column_if_missing(conn, 'events', 'ttl_hours', 'FLOAT', 'NULL')
    await add_column_if_missing(conn, 'events', 'engaged_at', 'TIMESTAMP', 'NULL')
    await add_column_if_missing(conn, 'events', 'outcome', 'TEXT', 'NULL')


async def init_db():
    db = await get_db()
    for statement in SCHEMA.split(';'):
        statement = statement.strip()
        if statement:
            await db.execute(statement)
    await db.commit()

    # Run versioned migrations (additive schema changes)
    await run_migrations(db)

    # Cold memory vector table (Phase 2) — requires sqlite-vec extension
    if COLD_SEARCH_ENABLED:
        try:
            await db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS cold_memory_vec USING vec0(
                    embedding float[1536],
                    source_type text,
                    +source_id text,
                    +text_content text,
                    +ts_iso text,
                    +embed_model text
                )
            """)
            await db.commit()
        except Exception as e:
            print(f"[DB] Failed to create cold_memory_vec table: {e}")

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

    # Legacy migration: cycle_log columns from self-state continuity patch
    # (kept for DBs created before migration framework existed)
    for col, col_type in [('body_state', 'TEXT'), ('gaze', 'TEXT'),
                          ('next_cycle_hints', 'JSON')]:
        await add_column_if_missing(db, 'cycle_log', col, col_type)


# ─── Event Store ───

async def append_event(event: Event):
    await _exec_write(
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
    await _exec_write(
        "INSERT OR IGNORE INTO inbox (event_id, priority) VALUES (?, ?)",
        (event_id, priority)
    )


async def inbox_get_unread() -> list[Event]:
    db = await get_db()
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
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
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
    await _exec_write(
        "UPDATE inbox SET read_at = ? WHERE event_id = ?",
        (datetime.now(timezone.utc).isoformat(), event_id)
    )


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
    kwargs['updated_at'] = datetime.now(timezone.utc).isoformat()
    if 'room_arrangement' in kwargs:
        kwargs['room_arrangement'] = json.dumps(kwargs['room_arrangement'])
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    await _exec_write(f"UPDATE room_state SET {sets} WHERE id = 1", tuple(vals))


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
    await _exec_write(
        """UPDATE drives_state SET
           social_hunger=?, curiosity=?, expression_need=?, rest_need=?,
           energy=?, mood_valence=?, mood_arousal=?, updated_at=?
           WHERE id = 1""",
        (d.social_hunger, d.curiosity, d.expression_need, d.rest_need,
         d.energy, d.mood_valence, d.mood_arousal,
         datetime.now(timezone.utc).isoformat())
    )


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
    for k in ('started_at', 'last_activity'):
        if k in kwargs and isinstance(kwargs[k], datetime):
            kwargs[k] = kwargs[k].isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    await _exec_write(f"UPDATE engagement_state SET {sets} WHERE id = 1", tuple(vals))


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
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
        "INSERT OR IGNORE INTO visitors (id, visit_count, first_visit, last_visit) VALUES (?, 1, ?, ?)",
        (visitor_id, now, now)
    )
    return await get_visitor(visitor_id)


async def update_visitor(visitor_id: str, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [visitor_id]
    await _exec_write(f"UPDATE visitors SET {sets} WHERE id = ?", tuple(vals))


async def increment_visit(visitor_id: str):
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
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
    await _exec_write(
        """INSERT INTO visitor_traits
           (id, visitor_id, trait_category, trait_key, trait_value, observed_at, source_event_id, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), visitor_id, trait_category, trait_key, trait_value,
         datetime.now(timezone.utc).isoformat(), source_event_id, confidence)
    )


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
    await _exec_write("UPDATE visitor_traits SET stability = ? WHERE id = ?", (stability, trait_id))


async def update_trait_status(trait_id: str, status: str):
    await _exec_write("UPDATE visitor_traits SET status = ? WHERE id = ?", (status, trait_id))


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
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
        """INSERT INTO totems
           (id, visitor_id, entity, weight, context, category, first_seen, last_referenced, source_event_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), visitor_id, entity, weight, context, category, now, now, source_event_id)
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
        await _exec_write(f"UPDATE totems SET {', '.join(updates)} {where}", tuple(vals))


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
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
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
    jid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
        """INSERT INTO journal_entries (id, content, mood, day_alive, tags, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (jid, content, mood, day_alive, json.dumps(tags or []), now)
    )
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
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
        """INSERT INTO daily_summaries
           (id, day_number, date, journal_entry_id, summary_bullets, emotional_arc, notable_totems, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), summary.get('day_number'), summary.get('date'),
         summary.get('journal_entry_id'), json.dumps(summary.get('summary_bullets', [])),
         summary.get('emotional_arc'), json.dumps(summary.get('notable_totems', [])), now)
    )


# ─── Conversation Log ───

async def append_conversation(visitor_id: str, role: str, text: str):
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
        "INSERT INTO conversation_log (id, visitor_id, role, text, ts) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), visitor_id, role, text, now)
    )


async def mark_session_boundary(visitor_id: str):
    """Insert a session boundary marker so get_recent_conversation only returns current session."""
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
        "INSERT INTO conversation_log (id, visitor_id, role, text, ts) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), visitor_id, 'system', '__session_boundary__', now)
    )


async def get_recent_conversation(visitor_id: str, limit: int = 10) -> list[dict]:
    """Get recent conversation for visitor, scoped to current session."""
    conn = await get_db()
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


# ─── Cycle Log ───

async def log_cycle(log: dict):
    await _exec_write(
        """INSERT INTO cycle_log
           (id, mode, drives, focus_salience, focus_type, routing_focus,
            token_budget, memory_count, internal_monologue, dialogue,
            expression, body_state, gaze, actions, dropped,
            next_cycle_hints, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (log['id'], log['mode'], json.dumps(log.get('drives', {})),
         log.get('focus_salience'), log.get('focus_type'),
         log.get('routing_focus'), log.get('token_budget'),
         log.get('memory_count'), log.get('internal_monologue'),
         log.get('dialogue'), log.get('expression'),
         log.get('body_state', 'sitting'), log.get('gaze', 'at_visitor'),
         json.dumps(log.get('actions', [])), json.dumps(log.get('dropped', [])),
         json.dumps(log.get('next_cycle_hints', [])),
         datetime.now(timezone.utc).isoformat())
    )


async def get_last_cycle_log() -> dict | None:
    """Fetch the most recent cycle_log entry for self_state assembly."""
    conn = await get_db()
    cursor = await conn.execute(
        """SELECT body_state, gaze, expression, internal_monologue,
                  actions, next_cycle_hints, dialogue, mode
           FROM cycle_log ORDER BY ts DESC LIMIT 1"""
    )
    row = await cursor.fetchone()
    if not row:
        return None
    raw_hints = json.loads(row['next_cycle_hints']) if row['next_cycle_hints'] else []
    return {
        'body_state': row['body_state'] or 'sitting',
        'gaze': row['gaze'] or 'at_visitor',
        'expression': row['expression'] or 'neutral',
        'internal_monologue': row['internal_monologue'] or '',
        'actions': json.loads(row['actions']) if row['actions'] else [],
        'next_cycle_hints': raw_hints if isinstance(raw_hints, list) else [],
        'dialogue': row['dialogue'],
        'mode': row['mode'],
    }


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


# ─── Peek Queries (read-only, no events) ───

async def get_all_journal() -> list[JournalEntry]:
    conn = await get_db()
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


async def get_collection_by_location(location: str) -> list[CollectionItem]:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM collection_items WHERE location = ? ORDER BY created_at DESC",
        (location,)
    )
    rows = await cursor.fetchall()
    return [_row_to_collection(r) for r in rows]


async def get_all_totems(limit: int = 100) -> list[Totem]:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM totems ORDER BY weight DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    return [_row_to_totem(r) for r in rows]


async def get_recent_events(limit: int = 20) -> list[Event]:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    return list(reversed([_row_to_event(r) for r in rows]))


async def get_visitor_count_today() -> int:
    conn = await get_db()
    today_jst = datetime.now(JST).date().isoformat()
    cursor = await conn.execute(
        "SELECT COUNT(DISTINCT source) as cnt FROM events "
        "WHERE event_type = 'visitor_connect' AND date(ts, '+9 hours') = ?",
        (today_jst,)
    )
    row = await cursor.fetchone()
    return row['cnt'] if row else 0


async def get_days_alive() -> int:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT MIN(created_at) as first FROM events"
    )
    row = await cursor.fetchone()
    if not row or not row['first']:
        return 0
    first = datetime.fromisoformat(row['first'])
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(1, (now - first).days + 1)


async def get_last_creative_cycle() -> Optional[dict]:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM cycle_log WHERE mode IN ('express', 'autonomous') ORDER BY ts DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return {
        'mode': row['mode'],
        'ts': row['ts'],
        'dialogue': row['dialogue'],
        'internal_monologue': row['internal_monologue'],
    }


# ─── Day Memory ───

_MAX_DAY_MEMORIES = 30


async def insert_day_memory(moment) -> None:
    """Insert a day memory entry. Enforces MAX_DAY_MEMORIES cap.

    Atomic: count + evict + insert run inside a single transaction to
    prevent concurrent inserts from overshooting the cap.
    """
    async with transaction():
        conn = await get_db()

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
             json.dumps(moment.tags), datetime.now(timezone.utc).isoformat())
        )
        # commit is handled by transaction().__aexit__


def _jst_today_start_utc() -> str:
    """Return start of today (JST) as UTC ISO string for day_memory filtering.

    Day memory is scoped to the current JST day. This computes midnight JST
    converted to UTC so we can filter the UTC timestamps stored in day_memory.
    """
    now_jst = datetime.now(JST)
    start_of_day_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_day_utc = start_of_day_jst.astimezone(timezone.utc)
    return start_of_day_utc.isoformat()


async def get_day_memory(
    visitor_id: str = None,
    limit: int = 3,
    min_salience: float = 0.3,
) -> list:
    """Get today's day memory entries, optionally filtered by visitor and salience."""
    conn = await get_db()
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


async def get_unprocessed_day_memory(
    min_salience: float = 0.4,
    limit: int = 7,
) -> list:
    """Get ALL unprocessed day memory entries for sleep consolidation.

    No date filter here — sleep runs at 03:00 JST and must consolidate
    moments from the entire prior waking period (which spans two calendar
    days, e.g. 06:00 JST yesterday through 02:00 JST today). The
    delete_stale_day_memory() safety net prevents unbounded accumulation.
    """
    conn = await get_db()
    cursor = await conn.execute(
        """SELECT * FROM day_memory
           WHERE processed_at IS NULL AND salience >= ?
           ORDER BY salience DESC LIMIT ?""",
        (min_salience, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_day_memory(r) for r in rows]


async def mark_day_memory_processed(moment_id: str) -> None:
    """Stamp processed_at on a day memory entry."""
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
        "UPDATE day_memory SET processed_at = ? WHERE id = ?",
        (now, moment_id)
    )


async def increment_day_memory_retry(moment_id: str) -> None:
    """Increment retry_count for a failed day memory entry.

    This is a standalone write — commits even when the calling
    transaction has rolled back."""
    await _exec_write(
        "UPDATE day_memory SET retry_count = retry_count + 1 WHERE id = ?",
        (moment_id,)
    )


async def delete_processed_day_memory() -> None:
    """Delete day_memory rows where processed_at IS NOT NULL.

    Calls _exec_write() directly — _exec_write() already acquires
    _write_lock when called outside a transaction. Do NOT double-lock."""
    await _exec_write(
        "DELETE FROM day_memory WHERE processed_at IS NOT NULL"
    )


async def delete_stale_day_memory(max_age_days: int = 2) -> None:
    """Delete day_memory rows older than max_age_days, regardless of status.

    Safety net: prevents unprocessed moments from leaking across day
    boundaries if sleep didn't process them (e.g. only top-K were selected).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    await _exec_write(
        "DELETE FROM day_memory WHERE ts < ?",
        (cutoff,)
    )


async def get_daily_summary_for_today() -> Optional[dict]:
    """Check if a daily summary already exists for today (JST)."""
    conn = await get_db()
    today_jst = datetime.now(JST).date().isoformat()
    cursor = await conn.execute(
        "SELECT * FROM daily_summaries WHERE date = ?",
        (today_jst,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


def _row_to_day_memory(row):
    """Convert a DB row to a DayMemoryEntry."""
    from pipeline.day_memory import DayMemoryEntry
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
        conn = await get_db()

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
    conn = await get_db()
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
    conn = await get_db()
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

    conn = await get_db()
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
    conn = await get_db()

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
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM cycle_log WHERE id = ?",
        (cycle_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_cold_embedding_count() -> int:
    """Return total number of embeddings in cold_memory_vec."""
    conn = await get_db()
    try:
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM cold_memory_vec"
        )
        row = await cursor.fetchone()
        return row['cnt'] if row else 0
    except Exception:
        return 0

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
    conn = await get_db()
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
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM threads WHERE id = ?", (thread_id,)
    )
    row = await cursor.fetchone()
    return _row_to_thread(row) if row else None


async def get_thread_by_title(title: str) -> Optional[Thread]:
    """Exact case-insensitive match only. Returns None if 0 or >1 matches."""
    conn = await get_db()
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
    now = datetime.now(timezone.utc).isoformat()
    await _exec_write(
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
    now = datetime.now(timezone.utc).isoformat()
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
    await _exec_write(
        f"UPDATE threads SET {', '.join(updates)} WHERE id = ?",
        tuple(vals)
    )


async def get_dormant_threads(older_than_hours: int = 48) -> list[Thread]:
    """Get active threads untouched for >older_than_hours."""
    conn = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
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
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    conn = await get_db()
    cursor = await conn.execute(
        """UPDATE threads SET status = 'archived'
           WHERE status = 'dormant' AND last_touched < ?""",
        (cutoff,)
    )
    await conn.commit()
    return cursor.rowcount


async def get_thread_count_by_status() -> dict:
    """Get thread counts by status. For peek command and sleep digest."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT status, COUNT(*) as cnt FROM threads GROUP BY status"
    )
    rows = await cursor.fetchall()
    return {row['status']: row['cnt'] for row in rows}


# ─── Arbiter State ───

async def load_arbiter_state() -> dict:
    """Load arbiter state from DB. Returns dict matching ArbiterState fields."""
    conn = await get_db()
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
            'current_date_jst': datetime.now(JST).date().isoformat(),
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
    await _exec_write(
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
    now = datetime.now(timezone.utc).isoformat()
    try:
        await _exec_write(
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
    conn = await get_db()
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
    conn = await get_db()
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
    await _exec_write(
        f"UPDATE content_pool SET {', '.join(sets)} WHERE id = ?",
        tuple(vals)
    )


async def update_event_outcome(event_id: str, outcome: str,
                                engaged_at: datetime = None) -> None:
    """Update an event's outcome and engaged_at timestamp.

    Used by executor to couple pool status changes with their source events.
    """
    ts = (engaged_at or datetime.now(timezone.utc)).isoformat()
    await _exec_write(
        "UPDATE events SET outcome = ?, engaged_at = ? WHERE id = ?",
        (outcome, ts, event_id)
    )


async def get_pool_stats() -> dict:
    """Get count of pool items by status."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT status, COUNT(*) FROM content_pool GROUP BY status"
    )
    rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def expire_pool_items():
    """Remove expired pool items (TTL-based)."""
    await _exec_write(
        """DELETE FROM content_pool
           WHERE ttl_hours IS NOT NULL
           AND status = 'unseen'
           AND julianday('now') - julianday(added_at) > ttl_hours / 24.0"""
    )


async def cap_unseen_pool(max_unseen: int = 50):
    """Remove oldest unseen items when pool exceeds cap."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM content_pool WHERE status = 'unseen'"
    )
    row = await cursor.fetchone()
    count = row[0] if row else 0
    if count > max_unseen:
        excess = count - max_unseen
        await _exec_write(
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
    conn = await get_db()
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
