"""SQLite + sqlite-vec storage adapter for alive-memory.

Uses aiosqlite for async access and optionally sqlite-vec for vector search.
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
    ConsolidationReport,
    DriveState,
    EventType,
    Memory,
    MemoryType,
    MoodState,
    SelfModel,
)

_MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"


def _serialize_embedding(embedding: list[float] | None) -> bytes | None:
    """Pack a float list into a compact binary blob."""
    if embedding is None:
        return None
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(blob: bytes | None) -> list[float] | None:
    """Unpack a binary blob back into a float list."""
    if blob is None:
        return None
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_memory(row: aiosqlite.Row) -> Memory:
    """Convert a DB row to a Memory dataclass."""
    return Memory(
        id=row["id"],
        content=row["content"],
        memory_type=MemoryType(row["memory_type"]),
        strength=row["strength"],
        valence=row["valence"],
        formed_at=datetime.fromisoformat(row["formed_at"]),
        last_recalled=(
            datetime.fromisoformat(row["last_recalled"])
            if row["last_recalled"]
            else None
        ),
        recall_count=row["recall_count"],
        source_event=(
            EventType(row["source_event"]) if row["source_event"] else None
        ),
        drive_coupling=json.loads(row["drive_coupling"] or "{}"),
        embedding=_deserialize_embedding(row["embedding"]),
        metadata=json.loads(row["metadata"] or "{}"),
    )


class SQLiteStorage(BaseStorage):
    """SQLite-backed storage for alive-memory.

    Usage:
        storage = SQLiteStorage("path/to/memory.db")
        await storage.initialize()
        # ... use storage ...
        await storage.close()
    """

    def __init__(self, db_path: str = "memory.db", enable_vec: bool = False):
        self._db_path = db_path
        self._enable_vec = enable_vec
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

            if self._enable_vec:
                try:
                    import sqlite_vec
                    await self._db.enable_load_extension(True)
                    sqlite_vec.load(self._db._conn)
                    await self._db.enable_load_extension(False)
                except (ImportError, Exception) as e:
                    print(f"[Storage] sqlite-vec unavailable: {e}")

        return self._db

    async def _exec_write(self, sql: str, params: tuple = ()) -> None:
        """Execute a write with proper serialization."""
        conn = await self._get_db()
        if self._tx_depth.get() > 0:
            await conn.execute(sql, params)
        else:
            async with self._write_lock:
                await conn.execute(sql, params)
                await conn.commit()

    # ── Memory CRUD ──────────────────────────────────────────────

    async def store_memory(self, memory: Memory) -> str:
        if not memory.id:
            memory.id = str(uuid.uuid4())
        await self._exec_write(
            """INSERT INTO memories
               (id, content, memory_type, strength, valence, formed_at,
                last_recalled, recall_count, source_event, drive_coupling,
                embedding, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id,
                memory.content,
                memory.memory_type.value,
                memory.strength,
                memory.valence,
                memory.formed_at.isoformat(),
                memory.last_recalled.isoformat() if memory.last_recalled else None,
                memory.recall_count,
                memory.source_event.value if memory.source_event else None,
                json.dumps(memory.drive_coupling),
                _serialize_embedding(memory.embedding),
                json.dumps(memory.metadata),
            ),
        )
        # Update memory count
        conn = await self._get_db()
        async with self._write_lock:
            await conn.execute(
                "UPDATE cognitive_state SET memories_total = memories_total + 1 WHERE id = 1"
            )
            await conn.commit()
        return memory.id

    async def get_memory(self, memory_id: str) -> Optional[Memory]:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        )
        row = await cursor.fetchone()
        return _row_to_memory(row) if row else None

    async def search_memories(
        self,
        embedding: list[float],
        limit: int = 5,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[Memory]:
        conn = await self._get_db()
        # Brute-force cosine similarity search over stored embeddings
        cursor = await conn.execute(
            "SELECT * FROM memories WHERE embedding IS NOT NULL"
        )
        rows = await cursor.fetchall()

        scored: list[tuple[float, Memory]] = []
        for row in rows:
            mem = _row_to_memory(row)
            if mem.embedding is None:
                continue

            # Apply filters
            if filters:
                if "memory_type" in filters and mem.memory_type.value != filters["memory_type"]:
                    continue
                if "min_strength" in filters and mem.strength < filters["min_strength"]:
                    continue

            score = _cosine_similarity(embedding, mem.embedding)
            scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:limit]]

    async def search_memories_by_text(
        self, query: str, limit: int = 5
    ) -> list[Memory]:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT * FROM memories WHERE content LIKE ? ORDER BY strength DESC LIMIT ?",
            (f"%{query}%", limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_memory(row) for row in rows]

    async def update_memory_strength(
        self, memory_id: str, strength: float
    ) -> None:
        await self._exec_write(
            "UPDATE memories SET strength = ? WHERE id = ?",
            (max(0.0, min(1.0, strength)), memory_id),
        )

    async def update_memory_recall(self, memory_id: str) -> None:
        await self._exec_write(
            "UPDATE memories SET recall_count = recall_count + 1, last_recalled = ? WHERE id = ?",
            (_now_iso(), memory_id),
        )

    async def delete_memory(self, memory_id: str) -> None:
        await self._exec_write(
            "DELETE FROM memories WHERE id = ?", (memory_id,)
        )
        conn = await self._get_db()
        async with self._write_lock:
            await conn.execute(
                "UPDATE cognitive_state SET memories_total = MAX(0, memories_total - 1) WHERE id = 1"
            )
            await conn.commit()

    async def get_memories_for_consolidation(
        self, min_age_hours: float = 1.0
    ) -> list[Memory]:
        conn = await self._get_db()
        cursor = await conn.execute(
            """SELECT * FROM memories
               WHERE formed_at <= datetime('now', ?)
               ORDER BY strength ASC""",
            (f"-{min_age_hours} hours",),
        )
        rows = await cursor.fetchall()
        return [_row_to_memory(row) for row in rows]

    async def merge_memories(
        self, source_ids: list[str], merged: Memory
    ) -> None:
        async with self._write_lock:
            conn = await self._get_db()
            self._tx_depth.set(self._tx_depth.get() + 1)
            try:
                await conn.execute("BEGIN IMMEDIATE")
                for sid in source_ids:
                    await conn.execute(
                        "DELETE FROM memories WHERE id = ?", (sid,)
                    )
                # Insert merged memory
                if not merged.id:
                    merged.id = str(uuid.uuid4())
                await conn.execute(
                    """INSERT INTO memories
                       (id, content, memory_type, strength, valence, formed_at,
                        last_recalled, recall_count, source_event, drive_coupling,
                        embedding, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        merged.id,
                        merged.content,
                        merged.memory_type.value,
                        merged.strength,
                        merged.valence,
                        merged.formed_at.isoformat(),
                        merged.last_recalled.isoformat() if merged.last_recalled else None,
                        merged.recall_count,
                        merged.source_event.value if merged.source_event else None,
                        json.dumps(merged.drive_coupling),
                        _serialize_embedding(merged.embedding),
                        json.dumps(merged.metadata),
                    ),
                )
                # Adjust count: removed N, added 1
                count_delta = 1 - len(source_ids)
                if count_delta != 0:
                    await conn.execute(
                        "UPDATE cognitive_state SET memories_total = MAX(0, memories_total + ?) WHERE id = 1",
                        (count_delta,),
                    )
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
            finally:
                self._tx_depth.set(self._tx_depth.get() - 1)

    async def count_memories(self) -> int:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT COUNT(*) FROM memories")
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
        return SelfModel(
            traits=json.loads(row["traits"] or "{}"),
            behavioral_summary=row["behavioral_summary"],
            drift_history=json.loads(row["drift_history"] or "[]"),
            version=row["version"],
            snapshot_at=(
                datetime.fromisoformat(row["snapshot_at"])
                if row["snapshot_at"]
                else None
            ),
        )

    async def save_self_model(self, model: SelfModel) -> None:
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

    async def log_consolidation(self, report: ConsolidationReport) -> None:
        await self._exec_write(
            """INSERT INTO consolidation_log
               (id, memories_strengthened, memories_weakened, memories_pruned,
                memories_merged, dreams, reflections, identity_drift,
                duration_ms, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                report.memories_strengthened,
                report.memories_weakened,
                report.memories_pruned,
                report.memories_merged,
                json.dumps(report.dreams),
                json.dumps(report.reflections),
                json.dumps(report.identity_drift) if report.identity_drift else None,
                report.duration_ms,
                _now_iso(),
            ),
        )

    # ── Lifecycle ────────────────────────────────────────────────

    async def initialize(self) -> None:
        conn = await self._get_db()
        migration_file = _MIGRATIONS_DIR / "001_initial.sql"
        if migration_file.exists():
            sql = migration_file.read_text()
            for stmt in sql.split(";"):
                cleaned = "\n".join(
                    line
                    for line in stmt.strip().splitlines()
                    if not line.strip().startswith("--")
                ).strip()
                if cleaned:
                    await conn.execute(cleaned)
            await conn.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
