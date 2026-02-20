"""sim.db — In-memory SQLite database for simulation.

Creates a fresh in-memory SQLite database with the full schema.
Core tables are created first, then migration files are applied
(with errors handled gracefully since some migrations reference
tables created by the real db.py's run_migrations()).

Usage:
    from sim.db import InMemoryDB
    db = await InMemoryDB.create()
    # Now use db for queries
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


# Path to migrations directory (relative to project root)
_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


class InMemoryDB:
    """SQLite in-memory database for simulation. Full schema, no disk I/O.

    Uses synchronous sqlite3 (not aiosqlite) for simplicity and speed.
    Simulation code doesn't need true async DB — it's all in-process.
    """

    def __init__(self, migrations_dir: Path | None = None):
        self.migrations_dir = migrations_dir or _MIGRATIONS_DIR
        self.conn: sqlite3.Connection | None = None

    async def init(self):
        """Initialize the in-memory database with full schema."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._create_core_tables()
        self._run_migrations()

    def _create_core_tables(self):
        """Create all core tables needed for simulation."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                source TEXT,
                content TEXT,
                metadata TEXT,
                salience REAL DEFAULT 0.5,
                salience_dynamic REAL DEFAULT 0.0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS drives_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                social_hunger REAL DEFAULT 0.5,
                curiosity REAL DEFAULT 0.5,
                expression_need REAL DEFAULT 0.3,
                rest_need REAL DEFAULT 0.2,
                energy REAL DEFAULT 0.8,
                mood_valence REAL DEFAULT 0.0,
                mood_arousal REAL DEFAULT 0.3,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS drives_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                social_hunger REAL,
                curiosity REAL,
                expression_need REAL,
                rest_need REAL,
                energy REAL,
                mood_valence REAL,
                mood_arousal REAL,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS engagement_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                status TEXT DEFAULT 'none',
                visitor_id TEXT,
                context_id TEXT,
                started_at TEXT,
                last_activity TEXT,
                turn_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS room_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                time_of_day TEXT DEFAULT 'morning',
                weather TEXT DEFAULT 'clear',
                shop_status TEXT DEFAULT 'open',
                ambient_music TEXT,
                room_arrangement TEXT DEFAULT '{}',
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS cycle_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_number INTEGER,
                routing_focus TEXT,
                trigger_type TEXT,
                action_taken TEXT,
                dialogue TEXT,
                internal_monologue TEXT,
                drives_snapshot TEXT,
                energy_spent REAL DEFAULT 0.0,
                tokens_used INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS memory_pool (
                id TEXT PRIMARY KEY,
                label TEXT,
                content TEXT,
                memory_type TEXT DEFAULT 'observation',
                salience REAL DEFAULT 0.5,
                created_at TEXT,
                last_accessed TEXT,
                access_count INTEGER DEFAULT 0,
                source_event_id TEXT,
                visitor_id TEXT,
                embedding BLOB
            );

            CREATE TABLE IF NOT EXISTS visitors (
                id TEXT PRIMARY KEY,
                name TEXT,
                trust_level TEXT DEFAULT 'stranger',
                visit_count INTEGER DEFAULT 0,
                first_visit TEXT,
                last_visit TEXT,
                summary TEXT,
                emotional_imprint TEXT,
                hands_state TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_summaries (
                id TEXT PRIMARY KEY,
                day_number INTEGER,
                date TEXT,
                summary TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS journal (
                id TEXT PRIMARY KEY,
                content TEXT,
                mood TEXT,
                day_alive INTEGER,
                tags TEXT DEFAULT '[]',
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS collection_items (
                id TEXT PRIMARY KEY,
                item_type TEXT,
                title TEXT,
                url TEXT,
                description TEXT,
                location TEXT DEFAULT 'shelf',
                origin TEXT DEFAULT 'appeared',
                gifted_by TEXT,
                her_feeling TEXT,
                emotional_tags TEXT DEFAULT '[]',
                display_note TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS totems (
                id TEXT PRIMARY KEY,
                entity TEXT,
                weight REAL DEFAULT 0.5,
                visitor_id TEXT,
                context TEXT,
                category TEXT,
                first_seen TEXT,
                last_referenced TEXT,
                source_event_id TEXT
            );

            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                thread_type TEXT,
                title TEXT,
                status TEXT DEFAULT 'open',
                priority REAL DEFAULT 0.5,
                content TEXT,
                resolution TEXT,
                created_at TEXT,
                last_touched TEXT,
                touch_count INTEGER DEFAULT 0,
                touch_reason TEXT,
                target_date TEXT,
                source_visitor_id TEXT,
                source_event_id TEXT,
                tags TEXT DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS llm_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_site TEXT,
                model TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                latency_ms INTEGER DEFAULT 0,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS day_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                moment_type TEXT,
                content TEXT,
                salience REAL DEFAULT 0.5,
                cycle_number INTEGER,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS llm_call_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_site TEXT,
                model TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                latency_ms INTEGER DEFAULT 0,
                timestamp TEXT
            );

            -- Seed singleton rows
            INSERT OR IGNORE INTO drives_state (id) VALUES (1);
            INSERT OR IGNORE INTO engagement_state (id) VALUES (1);
            INSERT OR IGNORE INTO room_state (id) VALUES (1);
        """)
        self.conn.commit()

    def _run_migrations(self):
        """Run migration files to add extra schema (tables, columns, indexes).

        Errors are caught per-migration since some migrations reference tables
        created by the real db.py's Python code rather than SQL files.
        """
        if not self.migrations_dir.exists():
            return
        for migration in sorted(self.migrations_dir.glob("*.sql")):
            sql = migration.read_text()
            try:
                self.conn.executescript(sql)
            except sqlite3.OperationalError:
                pass  # Table already exists or references missing table
        self.conn.commit()

    async def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    async def execute(self, sql: str, params: tuple = ()):
        """Execute a SQL statement."""
        return self.conn.execute(sql, params)

    async def executemany(self, sql: str, params_seq):
        """Execute a SQL statement with multiple parameter sets."""
        return self.conn.executemany(sql, params_seq)

    async def fetchone(self, sql: str, params: tuple = ()):
        """Execute and fetch one row."""
        cursor = self.conn.execute(sql, params)
        return cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        """Execute and fetch all rows."""
        cursor = self.conn.execute(sql, params)
        return cursor.fetchall()

    async def commit(self):
        """Commit pending changes."""
        self.conn.commit()

    @classmethod
    async def create(cls, migrations_dir: Path | None = None) -> "InMemoryDB":
        """Factory method — create and initialize an InMemoryDB."""
        db = cls(migrations_dir=migrations_dir)
        await db.init()
        return db
