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

import os
import sqlite3
from pathlib import Path


# Path to migrations directory (relative to project root)
_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

# Hard guard: simulation must NEVER touch production databases.
PRODUCTION_DB_NAMES = frozenset({
    "shopkeeper.db", "shopkeeper-prod.db", "taste_sim.db",
})


def _assert_not_production(path: str) -> None:
    """Refuse to open anything that looks like the production DB."""
    if path == ":memory:":
        return
    basename = os.path.basename(path)
    if basename in PRODUCTION_DB_NAMES:
        raise RuntimeError(
            f"REFUSED: sim tried to open production DB '{path}'. "
            f"Use --db to specify a separate file."
        )


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
        _assert_not_production(":memory:")
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

            -- Taste experiment tables (TASK-093)
            CREATE TABLE IF NOT EXISTS taste_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                cycle INTEGER NOT NULL,
                condition_accuracy REAL,
                rarity_authenticity REAL,
                price_fairness REAL,
                historical_significance REAL,
                aesthetic_quality REAL,
                provenance REAL,
                personal_resonance REAL,
                weighted_score REAL,
                decision TEXT,
                confidence REAL,
                features TEXT,
                rationale TEXT,
                parse_success INTEGER DEFAULT 0,
                feature_count INTEGER DEFAULT 0,
                categories_covered INTEGER DEFAULT 0,
                comparative_citations INTEGER DEFAULT 0,
                causal_chain_steps INTEGER DEFAULT 0,
                word_count INTEGER DEFAULT 0,
                feature_density REAL DEFAULT 0.0,
                capital_before REAL,
                inventory_count_before INTEGER,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS taste_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                eval_id INTEGER,
                cycle_acquired INTEGER,
                cycle_outcome INTEGER,
                buy_price REAL,
                sell_price REAL,
                profit REAL,
                time_to_sell INTEGER,
                outcome_category TEXT,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS taste_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                eval_id INTEGER,
                cycle_acquired INTEGER,
                buy_price REAL,
                status TEXT DEFAULT 'held',
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

    # ── Taste experiment helpers (TASK-093) ─────────────────────────

    async def record_taste_evaluation(self, ev) -> int:
        """Record a taste evaluation and return its rowid."""
        import json
        cursor = self.conn.execute(
            """INSERT INTO taste_evaluations (
                item_id, cycle,
                condition_accuracy, rarity_authenticity, price_fairness,
                historical_significance, aesthetic_quality, provenance,
                personal_resonance, weighted_score, decision, confidence,
                features, rationale, parse_success,
                feature_count, categories_covered, comparative_citations,
                causal_chain_steps, word_count, feature_density,
                capital_before, inventory_count_before
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ev.item_id, ev.cycle,
                ev.condition_accuracy, ev.rarity_authenticity, ev.price_fairness,
                ev.historical_significance, ev.aesthetic_quality, ev.provenance,
                ev.personal_resonance, ev.weighted_score, ev.decision,
                ev.confidence,
                json.dumps(ev.features) if ev.features else None,
                ev.rationale, int(ev.parse_success),
                ev.feature_count, ev.categories_covered_count,
                ev.comparative_citations, ev.causal_chain_steps,
                ev.word_count, ev.feature_density,
                ev.capital_remaining, ev.inventory_count,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    async def record_taste_acquisition(
        self, item_id: str, eval_id: int, cycle: int, price: float
    ) -> int:
        """Record an item entering inventory."""
        cursor = self.conn.execute(
            """INSERT INTO taste_inventory
               (item_id, eval_id, cycle_acquired, buy_price, status)
               VALUES (?,?,?,?,?)""",
            (item_id, eval_id, cycle, price, "held"),
        )
        self.conn.commit()
        return cursor.lastrowid

    async def record_taste_outcome(
        self, item_id: str, eval_id: int | None,
        cycle_acquired: int, cycle_outcome: int,
        buy_price: float, sell_price: float | None,
        profit: float, time_to_sell: int | None,
        outcome_category: str,
    ):
        """Record a resolved outcome."""
        self.conn.execute(
            """INSERT INTO taste_outcomes
               (item_id, eval_id, cycle_acquired, cycle_outcome,
                buy_price, sell_price, profit, time_to_sell,
                outcome_category)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item_id, eval_id, cycle_acquired, cycle_outcome,
             buy_price, sell_price, profit, time_to_sell,
             outcome_category),
        )
        # Mark inventory item as sold
        self.conn.execute(
            """UPDATE taste_inventory SET status = 'sold'
               WHERE item_id = ? AND status = 'held'""",
            (item_id,),
        )
        self.conn.commit()

    async def get_taste_evaluation_history(self, limit: int = 20) -> list:
        """Get recent evaluations for prompt context."""
        rows = self.conn.execute(
            """SELECT item_id, decision, weighted_score, cycle
               FROM taste_evaluations
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    async def get_taste_inventory_state(self, daily_capital: float) -> dict:
        """Get current inventory state for prompt context."""
        held = self.conn.execute(
            """SELECT COUNT(*) as count, COALESCE(SUM(buy_price), 0) as total
               FROM taste_inventory WHERE status = 'held'"""
        ).fetchone()
        return {
            "items_held": held["count"],
            "capital_invested": held["total"],
        }

    async def get_taste_pending_outcomes(
        self, current_cycle: int, delay: int
    ) -> list:
        """Get items ready for outcome resolution."""
        rows = self.conn.execute(
            """SELECT i.item_id, i.eval_id, i.cycle_acquired, i.buy_price
               FROM taste_inventory i
               WHERE i.status = 'held'
                 AND (? - i.cycle_acquired) >= ?""",
            (current_cycle, delay),
        ).fetchall()
        return [dict(r) for r in rows]

    async def get_all_taste_evaluations(self) -> list:
        """Get all taste evaluations for scoring."""
        rows = self.conn.execute(
            """SELECT * FROM taste_evaluations ORDER BY id"""
        ).fetchall()
        return [dict(r) for r in rows]

    # ── End taste helpers ─────────────────────────────────────────

    @classmethod
    async def create(cls, migrations_dir: Path | None = None) -> "InMemoryDB":
        """Factory method — create and initialize an InMemoryDB."""
        db = cls(migrations_dir=migrations_dir)
        await db.init()
        return db
