"""db.connection — Connection management, transactions, schema, and migrations."""

import asyncio
import aiosqlite
import contextvars
import json
import os
import pathlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import clock


COLD_SEARCH_ENABLED = os.getenv('COLD_SEARCH_ENABLED', 'false').lower() == 'true'

# The shopkeeper lives in JST. All "today" boundaries use JST.
JST = timezone(timedelta(hours=9))

DB_PATH = os.environ.get('SHOPKEEPER_DB_PATH', 'data/shopkeeper.db')

_db: Optional[aiosqlite.Connection] = None


PRODUCTION_DB_NAMES = frozenset({"shopkeeper.db", "shopkeeper-prod.db"})


def set_db_path(path: str):
    """Override DB_PATH for simulation. Must be called before first get_db()."""
    global DB_PATH, _db
    if _db is not None:
        raise RuntimeError("set_db_path() must be called before first get_db()")
    basename = os.path.basename(path)
    if basename in PRODUCTION_DB_NAMES:
        raise RuntimeError(
            f"REFUSED: set_db_path() tried to open production DB '{path}'. "
            f"Use a different filename (e.g. --output /tmp/sim/ --run-label my_run)."
        )
    DB_PATH = path


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        db_path = pathlib.Path(DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(db_path))
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

CREATE TABLE IF NOT EXISTS text_fragments (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    fragment_type TEXT NOT NULL,
    cycle_id TEXT,
    thread_id TEXT,
    visitor_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fragments_created ON text_fragments(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fragments_type ON text_fragments(fragment_type);

CREATE TABLE IF NOT EXISTS shelf_assignments (
    slot_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    item_description TEXT,
    sprite_filename TEXT,
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_tokens (
    token TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    uses_remaining INTEGER,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_call_log (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    cycle_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_llm_log_date ON llm_call_log(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_log_purpose ON llm_call_log(purpose);
"""


async def add_column_if_missing(conn, table: str, column: str,
                                col_type: str, default=None):
    """Add a column to a table if it doesn't already exist.

    SQLite lacks ADD COLUMN IF NOT EXISTS, so we check PRAGMA table_info.
    Skips silently if the table itself doesn't exist (migrations create it).
    """
    cursor = await conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in await cursor.fetchall()}
    if not existing:
        # Table doesn't exist yet — migration will create it with all columns
        return
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

    # Scan migrations/ directory — three levels up: db/ → engine/ → repo root
    migrations_dir = pathlib.Path(__file__).parent.parent.parent / 'migrations'
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

        # Runtime migration event (best-effort; runtime_event_log may not exist yet).
        try:
            from runtime_context import get_boot_cycle_id, get_run_id
            now = clock.now_utc().isoformat()
            await conn.execute(
                """INSERT INTO runtime_event_log
                   (id, timestamp_utc, run_id, cycle_id, event_type, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    now,
                    get_run_id(),
                    get_boot_cycle_id(),
                    'db_migration',
                    json.dumps({'version': version, 'filename': f.name}, ensure_ascii=True),
                ),
            )
            await conn.commit()
        except Exception:
            pass


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

    # Manager-injected memories — regular table, always available (no vec0 dependency)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS manager_memories (
            source_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL DEFAULT 'manager_backstory',
            text_content TEXT NOT NULL,
            title TEXT,
            ts_iso TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'manager_injected'
        )
    """)
    await db.commit()

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
            # Backfill origin table for pre-existing cold memories (migration 094
            # cannot reference cold_memory_vec because it's created here, after migrations).
            try:
                await db.execute(
                    "INSERT OR IGNORE INTO cold_memory_origin (source_id, origin) "
                    "SELECT source_id, 'organic' FROM cold_memory_vec"
                )
                await db.commit()
            except Exception:
                pass  # cold_memory_origin table may not exist yet on first run
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

    # Observability wiring compatibility columns (additive; safe on every start)
    cycle_log_cols = [
        ('run_id', 'TEXT'),
        ('trace_id', 'TEXT'),
        ('budget_usd_daily_cap', 'REAL'),
        ('budget_spent_usd_today', 'REAL'),
        ('budget_remaining_usd_today', 'REAL'),
        ('budget_mode', 'TEXT'),
        ('governor_decision', 'TEXT'),
    ]
    for col, col_type in cycle_log_cols:
        await add_column_if_missing(db, 'cycle_log', col, col_type)

    llm_log_cols = [
        ('timestamp_utc', 'TEXT'),
        ('run_id', 'TEXT'),
        ('stage', 'TEXT'),
        ('prompt_tokens', 'INTEGER'),
        ('completion_tokens', 'INTEGER'),
        ('total_tokens', 'INTEGER'),
        ('success', 'INTEGER'),
        ('error_type', 'TEXT'),
        ('request_id', 'TEXT'),
        ('cache_hit', 'INTEGER'),
        ('used_cached_prompt', 'INTEGER'),
        ('input_hash', 'TEXT'),
        ('output_hash', 'TEXT'),
        ('trace_id', 'TEXT'),
    ]
    for col, col_type in llm_log_cols:
        await add_column_if_missing(db, 'llm_call_log', col, col_type)

    action_log_cols = [
        ('timestamp_utc', 'TEXT'),
        ('run_id', 'TEXT'),
        ('action_type', 'TEXT'),
        ('channel', 'TEXT'),
        ('reason', 'TEXT'),
        ('cooldown_state', 'TEXT'),
        ('rate_limit_remaining', 'INTEGER'),
        ('limiter_decision', 'TEXT'),
        ('action_payload_hash', 'TEXT'),
        ('target_id', 'TEXT'),
        ('trace_id', 'TEXT'),
    ]
    for col, col_type in action_log_cols:
        await add_column_if_missing(db, 'action_log', col, col_type)

    external_action_log_cols = [
        ('cycle_id', 'TEXT'),
        ('run_id', 'TEXT'),
        ('trace_id', 'TEXT'),
        ('limiter_decision', 'TEXT'),
        ('cooldown_state', 'TEXT'),
        ('rate_limit_remaining', 'INTEGER'),
    ]
    for col, col_type in external_action_log_cols:
        await add_column_if_missing(db, 'external_action_log', col, col_type)
