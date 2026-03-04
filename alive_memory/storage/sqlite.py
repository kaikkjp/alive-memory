"""SQLite storage adapter for alive-memory (three-tier architecture).

Tier 1 — day_memory: ephemeral salient moments
Tier 3 — cold_embeddings: vector archive (sleep-only)
(Tier 2 is hot memory on disk, managed by hot/writer.py and hot/reader.py)
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import pathlib
import struct
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from alive_memory.storage.base import BaseStorage
from alive_memory.types import (
    CognitiveState,
    DayMoment,
    DriveState,
    EventType,
    MoodState,
    SelfModel,
    SleepReport,
)

_MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"


def _serialize_embedding(embedding: list[float] | None) -> bytes | None:
    if embedding is None:
        return None
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(blob: bytes | None) -> list[float] | None:
    if blob is None:
        return None
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_moment(row: aiosqlite.Row) -> DayMoment:
    return DayMoment(
        id=row["id"],
        content=row["content"],
        event_type=EventType(row["event_type"]),
        salience=row["salience"],
        valence=row["valence"],
        drive_snapshot=json.loads(row["drive_snapshot"] or "{}"),
        timestamp=datetime.fromisoformat(row["timestamp"]),
        processed=bool(row["processed"]),
        nap_processed=bool(row["nap_processed"]),
        metadata=json.loads(row["metadata"] or "{}"),
    )


class SQLiteStorage(BaseStorage):
    """SQLite-backed storage for alive-memory (three-tier).

    Usage:
        storage = SQLiteStorage("path/to/memory.db")
        await storage.initialize()
        # ... use storage ...
        await storage.close()
    """

    def __init__(self, db_path: str = "memory.db"):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()
        self._tx_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
            "_tx_depth", default=0
        )

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            path = pathlib.Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(str(path))
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA foreign_keys=ON")
        return self._db

    async def _exec_write(self, sql: str, params: tuple = ()) -> None:
        conn = await self._get_db()
        if self._tx_depth.get() > 0:
            await conn.execute(sql, params)
        else:
            async with self._write_lock:
                await conn.execute(sql, params)
                await conn.commit()

    # ── Day Memory (Tier 1) ───────────────────────────────────────

    async def record_moment(self, moment: DayMoment) -> str:
        if not moment.id:
            moment.id = str(uuid.uuid4())
        await self._exec_write(
            """INSERT INTO day_memory
               (id, content, event_type, salience, valence, drive_snapshot,
                timestamp, processed, nap_processed, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                moment.id,
                moment.content,
                moment.event_type.value,
                moment.salience,
                moment.valence,
                json.dumps(moment.drive_snapshot),
                moment.timestamp.isoformat(),
                int(moment.processed),
                int(moment.nap_processed),
                json.dumps(moment.metadata),
            ),
        )
        return moment.id

    async def get_unprocessed_moments(self, nap: bool = False) -> list[DayMoment]:
        conn = await self._get_db()
        if nap:
            cursor = await conn.execute(
                "SELECT * FROM day_memory WHERE nap_processed = 0 ORDER BY timestamp ASC"
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM day_memory WHERE processed = 0 ORDER BY timestamp ASC"
            )
        rows = await cursor.fetchall()
        return [_row_to_moment(row) for row in rows]

    async def mark_moment_processed(
        self, moment_id: str, nap: bool = False
    ) -> None:
        if nap:
            await self._exec_write(
                "UPDATE day_memory SET nap_processed = 1 WHERE id = ?",
                (moment_id,),
            )
        else:
            await self._exec_write(
                "UPDATE day_memory SET processed = 1 WHERE id = ?",
                (moment_id,),
            )

    async def flush_day_memory(self) -> int:
        conn = await self._get_db()
        async with self._write_lock:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM day_memory WHERE processed = 1"
            )
            row = await cursor.fetchone()
            count = row[0]
            await conn.execute("DELETE FROM day_memory WHERE processed = 1")
            await conn.commit()
        return count

    async def get_day_memory_count(self) -> int:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM day_memory WHERE processed = 0"
        )
        row = await cursor.fetchone()
        return row[0]

    async def get_lowest_salience_moment(self) -> Optional[DayMoment]:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT * FROM day_memory WHERE processed = 0 ORDER BY salience ASC LIMIT 1"
        )
        row = await cursor.fetchone()
        return _row_to_moment(row) if row else None

    async def delete_moment(self, moment_id: str) -> None:
        await self._exec_write(
            "DELETE FROM day_memory WHERE id = ?", (moment_id,)
        )

    async def get_recent_moment_content(
        self, window_minutes: int = 30
    ) -> list[str]:
        conn = await self._get_db()
        cursor = await conn.execute(
            """SELECT content FROM day_memory
               WHERE timestamp >= datetime('now', ?)
               ORDER BY timestamp DESC""",
            (f"-{window_minutes} minutes",),
        )
        rows = await cursor.fetchall()
        return [row["content"] for row in rows]

    # ── Cold Embeddings (Tier 3) ──────────────────────────────────

    async def store_cold_embedding(
        self,
        content: str,
        embedding: list[float],
        source_moment_id: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        embed_id = str(uuid.uuid4())
        await self._exec_write(
            """INSERT INTO cold_embeddings
               (id, content, embedding, source_moment_id, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                embed_id,
                content,
                _serialize_embedding(embedding),
                source_moment_id,
                json.dumps(metadata or {}),
                _now_iso(),
            ),
        )
        return embed_id

    async def search_cold(
        self,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT * FROM cold_embeddings"
        )
        rows = await cursor.fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            stored_emb = _deserialize_embedding(row["embedding"])
            if stored_emb is None:
                continue
            score = _cosine_similarity(embedding, stored_emb)
            scored.append((score, {
                "id": row["id"],
                "content": row["content"],
                "score": score,
                "metadata": json.loads(row["metadata"] or "{}"),
            }))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    async def count_cold_embeddings(self) -> int:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT COUNT(*) FROM cold_embeddings")
        row = await cursor.fetchone()
        return row[0]

    # ── Drive State ──────────────────────────────────────────────

    async def get_drive_state(self) -> DriveState:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT * FROM drive_state WHERE id = 1")
        row = await cursor.fetchone()
        return DriveState(
            curiosity=row["curiosity"],
            social=row["social"],
            expression=row["expression"],
            rest=row["rest"],
        )

    async def set_drive_state(self, state: DriveState) -> None:
        await self._exec_write(
            """UPDATE drive_state SET
               curiosity=?, social=?, expression=?, rest=?, updated_at=?
               WHERE id = 1""",
            (state.curiosity, state.social, state.expression, state.rest, _now_iso()),
        )

    # ── Mood State ───────────────────────────────────────────────

    async def get_mood_state(self) -> MoodState:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT * FROM mood_state WHERE id = 1")
        row = await cursor.fetchone()
        return MoodState(
            valence=row["valence"],
            arousal=row["arousal"],
            word=row["word"],
        )

    async def set_mood_state(self, state: MoodState) -> None:
        await self._exec_write(
            """UPDATE mood_state SET
               valence=?, arousal=?, word=?, updated_at=?
               WHERE id = 1""",
            (state.valence, state.arousal, state.word, _now_iso()),
        )

    # ── Cognitive State ──────────────────────────────────────────

    async def get_cognitive_state(self) -> CognitiveState:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT * FROM cognitive_state WHERE id = 1")
        cs_row = await cursor.fetchone()
        mood = await self.get_mood_state()
        drives = await self.get_drive_state()
        return CognitiveState(
            mood=mood,
            energy=cs_row["energy"],
            drives=drives,
            cycle_count=cs_row["cycle_count"],
            last_sleep=(
                datetime.fromisoformat(cs_row["last_sleep"])
                if cs_row["last_sleep"]
                else None
            ),
            memories_total=cs_row["memories_total"],
        )

    async def set_cognitive_state(self, state: CognitiveState) -> None:
        await self._exec_write(
            """UPDATE cognitive_state SET
               energy=?, cycle_count=?, last_sleep=?, memories_total=?, updated_at=?
               WHERE id = 1""",
            (
                state.energy,
                state.cycle_count,
                state.last_sleep.isoformat() if state.last_sleep else None,
                state.memories_total,
                _now_iso(),
            ),
        )
        await self.set_mood_state(state.mood)
        await self.set_drive_state(state.drives)

    # ── Self-Model ───────────────────────────────────────────────

    async def get_self_model(self) -> SelfModel:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT * FROM self_model WHERE id = 1")
        row = await cursor.fetchone()
        # Handle new columns gracefully (may not exist pre-migration)
        keys = row.keys() if row else []
        return SelfModel(
            traits=json.loads(row["traits"] or "{}"),
            behavioral_summary=row["behavioral_summary"],
            self_narrative=row["self_narrative"] if "self_narrative" in keys else "",
            behavioral_signature=json.loads(row["behavioral_signature"] or "{}") if "behavioral_signature" in keys else {},
            relational_stance=json.loads(row["relational_stance"] or "{}") if "relational_stance" in keys else {},
            drift_history=json.loads(row["drift_history"] or "[]"),
            version=row["version"],
            snapshot_at=(
                datetime.fromisoformat(row["snapshot_at"])
                if row["snapshot_at"]
                else None
            ),
            narrative_version=row["narrative_version"] if "narrative_version" in keys else 0,
        )

    async def save_self_model(self, model: SelfModel) -> None:
        # Check if new columns exist by trying the full update
        try:
            await self._exec_write(
                """UPDATE self_model SET
                   traits=?, behavioral_summary=?, self_narrative=?,
                   behavioral_signature=?, relational_stance=?,
                   drift_history=?, version=?, snapshot_at=?, narrative_version=?
                   WHERE id = 1""",
                (
                    json.dumps(model.traits),
                    model.behavioral_summary,
                    model.self_narrative,
                    json.dumps(model.behavioral_signature),
                    json.dumps(model.relational_stance),
                    json.dumps(model.drift_history),
                    model.version,
                    model.snapshot_at.isoformat() if model.snapshot_at else _now_iso(),
                    model.narrative_version,
                ),
            )
        except Exception:
            # Fallback: pre-migration schema without new columns
            await self._exec_write(
                """UPDATE self_model SET
                   traits=?, behavioral_summary=?, drift_history=?,
                   version=?, snapshot_at=?
                   WHERE id = 1""",
                (
                    json.dumps(model.traits),
                    model.behavioral_summary,
                    json.dumps(model.drift_history),
                    model.version,
                    model.snapshot_at.isoformat() if model.snapshot_at else _now_iso(),
                ),
            )

    # ── Drift Baseline ──────────────────────────────────────────

    async def get_drift_baseline(self) -> dict[str, Any]:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT * FROM drift_baseline WHERE id = 1")
        row = await cursor.fetchone()
        if not row:
            return {}
        return {
            "action_frequencies": json.loads(row["action_frequencies"] or "{}"),
            "scalar_metrics": json.loads(row["scalar_metrics"] or "{}"),
            "sample_count": row["sample_count"],
            "last_updated_cycle": row["last_updated_cycle"],
        }

    async def save_drift_baseline(self, baseline: dict[str, Any]) -> None:
        await self._exec_write(
            """UPDATE drift_baseline SET
               action_frequencies=?, scalar_metrics=?,
               sample_count=?, last_updated_cycle=?, updated_at=?
               WHERE id = 1""",
            (
                json.dumps(baseline.get("action_frequencies", {})),
                json.dumps(baseline.get("scalar_metrics", {})),
                baseline.get("sample_count", 0),
                baseline.get("last_updated_cycle", 0),
                _now_iso(),
            ),
        )

    # ── Evolution Decision Log ───────────────────────────────────

    async def log_evolution_decision(self, decision: dict[str, Any]) -> None:
        decision_id = decision.get("id", str(uuid.uuid4()))
        await self._exec_write(
            """INSERT INTO evolution_log
               (id, action, trait, reason, correction_value,
                composite_score, severity, cycle, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                decision.get("action", ""),
                decision.get("trait", ""),
                decision.get("reason", ""),
                decision.get("correction_value"),
                decision.get("composite_score"),
                decision.get("severity"),
                decision.get("cycle"),
                _now_iso(),
            ),
        )

    # ── Parameters ───────────────────────────────────────────────

    async def get_parameters(self) -> dict[str, float]:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT key, value FROM parameters")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def set_parameter(
        self, key: str, value: float, reason: str = ""
    ) -> None:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT value FROM parameters WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        old_value = row["value"] if row else None
        now = _now_iso()

        if row:
            await self._exec_write(
                "UPDATE parameters SET value=?, modified_by=?, modified_at=? WHERE key=?",
                (value, "system", now, key),
            )
        else:
            await self._exec_write(
                """INSERT INTO parameters (key, value, default_value, modified_by, modified_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, value, value, "system", now),
            )

        await self._exec_write(
            """INSERT INTO parameter_modifications
               (param_key, old_value, new_value, modified_by, reason, ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key, old_value, value, "system", reason, now),
        )

    # ── Cycle Log ────────────────────────────────────────────────

    async def log_cycle(self, entry: dict[str, Any]) -> None:
        cycle_id = entry.get("id", str(uuid.uuid4()))
        await self._exec_write(
            """INSERT INTO cycle_log
               (id, cycle_number, trigger_type, drives, mood, energy,
                memory_count, actions, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cycle_id,
                entry.get("cycle_number"),
                entry.get("trigger_type"),
                json.dumps(entry.get("drives", {})),
                json.dumps(entry.get("mood", {})),
                entry.get("energy"),
                entry.get("memory_count"),
                json.dumps(entry.get("actions", [])),
                entry.get("ts", _now_iso()),
            ),
        )

    async def get_cycle_count(self) -> int:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT COUNT(*) FROM cycle_log")
        row = await cursor.fetchone()
        return row[0]

    # ── Consolidation Log ────────────────────────────────────────

    async def log_consolidation(self, report: SleepReport) -> None:
        await self._exec_write(
            """INSERT INTO consolidation_log
               (id, moments_processed, journal_entries_written,
                reflections_written, cold_embeddings_added, cold_echoes_found,
                dreams, reflections, identity_drift, duration_ms, depth, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                report.moments_processed,
                report.journal_entries_written,
                report.reflections_written,
                report.cold_embeddings_added,
                report.cold_echoes_found,
                json.dumps(report.dreams),
                json.dumps(report.reflections),
                json.dumps(report.identity_drift) if report.identity_drift else None,
                report.duration_ms,
                report.depth,
                _now_iso(),
            ),
        )

    # ── Lifecycle ────────────────────────────────────────────────

    async def _run_migration(self, path: pathlib.Path) -> None:
        """Run a single SQL migration file, skipping comments."""
        conn = await self._get_db()
        sql = path.read_text()
        for stmt in sql.split(";"):
            cleaned = "\n".join(
                line
                for line in stmt.strip().splitlines()
                if not line.strip().startswith("--")
            ).strip()
            if cleaned:
                await conn.execute(cleaned)
        await conn.commit()

    async def _run_alter_columns(self) -> None:
        """Add new columns to self_model table. Idempotent (catches duplicate column errors)."""
        conn = await self._get_db()
        alters = [
            "ALTER TABLE self_model ADD COLUMN self_narrative TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE self_model ADD COLUMN behavioral_signature TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE self_model ADD COLUMN relational_stance TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE self_model ADD COLUMN narrative_version INTEGER NOT NULL DEFAULT 0",
        ]
        for sql in alters:
            try:
                await conn.execute(sql)
            except Exception:
                pass  # Column already exists
        await conn.commit()

    async def initialize(self) -> None:
        # Run 001_initial.sql
        migration_001 = _MIGRATIONS_DIR / "001_initial.sql"
        if migration_001.exists():
            await self._run_migration(migration_001)

        # Add new columns to self_model (idempotent ALTER TABLEs)
        await self._run_alter_columns()

        # Run 002_identity.sql (new tables for drift baseline + evolution log)
        migration_002 = _MIGRATIONS_DIR / "002_identity.sql"
        if migration_002.exists():
            await self._run_migration(migration_002)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
