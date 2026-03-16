"""SQLite storage adapter for alive-memory (three-tier architecture).

Tier 1 — day_memory: ephemeral salient moments
Tier 3 — cold_embeddings: vector archive (sleep-only)
(Tier 2 is hot memory on disk, managed by hot/writer.py and hot/reader.py)
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import pathlib
import re
import struct
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

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
    Totem,
    Visitor,
    VisitorTrait,
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
    return datetime.now(UTC).isoformat()


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
        self._db: aiosqlite.Connection | None = None
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
            count = int(row[0]) if row is not None else 0
            await conn.execute("DELETE FROM day_memory WHERE processed = 1")
            await conn.commit()
        return count

    async def flush_stale_moments(self, stale_hours: int = 72) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=stale_hours)
        conn = await self._get_db()
        async with self._write_lock:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM day_memory WHERE timestamp < ? AND processed = 0",
                (cutoff.isoformat(),),
            )
            row = await cursor.fetchone()
            count = int(row[0]) if row is not None else 0
            await conn.execute(
                "DELETE FROM day_memory WHERE timestamp < ? AND processed = 0",
                (cutoff.isoformat(),),
            )
            await conn.commit()
        return count

    async def get_day_memory_count(self) -> int:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM day_memory WHERE processed = 0"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def get_lowest_salience_moment(self) -> DayMoment | None:
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
        self, window_minutes: int = 30, *, reference_time: str | None = None
    ) -> list[str]:
        conn = await self._get_db()
        if reference_time:
            cursor = await conn.execute(
                """SELECT content FROM day_memory
                   WHERE timestamp >= strftime('%Y-%m-%dT%H:%M:%S+00:00', ?, ?)
                   ORDER BY timestamp DESC""",
                (reference_time, f"-{window_minutes} minutes"),
            )
        else:
            cursor = await conn.execute(
                """SELECT content FROM day_memory
                   WHERE timestamp >= strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', ?)
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
        metadata: dict[str, Any] | None = None,
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
        return int(row[0]) if row is not None else 0

    # ── Drive State ──────────────────────────────────────────────

    async def get_drive_state(self) -> DriveState:
        conn = await self._get_db()
        cursor = await conn.execute("SELECT * FROM drive_state WHERE id = 1")
        row = await cursor.fetchone()
        assert row is not None, "drive_state row with id=1 must exist"
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
        assert row is not None, "mood_state row with id=1 must exist"
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
        assert cs_row is not None, "cognitive_state row with id=1 must exist"
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
        assert row is not None, "self_model row with id=1 must exist"
        # Handle new columns gracefully (may not exist pre-migration)
        keys = row.keys()
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

    # ── Meta Experiments ─────────────────────────────────────────

    async def save_experiment(self, experiment: dict[str, Any]) -> None:
        await self._exec_write(
            """INSERT INTO meta_experiments
               (id, param_key, old_value, new_value, target_metric,
                metric_at_change, outcome, confidence, side_effects,
                created_at, evaluated_at, cycle_at_creation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment["id"],
                experiment["param_key"],
                experiment["old_value"],
                experiment["new_value"],
                experiment["target_metric"],
                experiment["metric_at_change"],
                experiment.get("outcome", "pending"),
                experiment.get("confidence", 0.5),
                json.dumps(experiment.get("side_effects", [])),
                experiment["created_at"],
                experiment.get("evaluated_at"),
                experiment.get("cycle_at_creation", 0),
            ),
        )

    async def get_pending_experiments(self, min_age_cycles: int = 0) -> list[dict[str, Any]]:
        conn = await self._get_db()
        cursor = await conn.execute(
            """SELECT * FROM meta_experiments
               WHERE outcome = 'pending'
                 AND cycle_at_creation + ? <= (SELECT COUNT(*) FROM cycle_log)""",
            (min_age_cycles,),
        )
        rows = await cursor.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            results.append({
                "id": row["id"],
                "param_key": row["param_key"],
                "old_value": row["old_value"],
                "new_value": row["new_value"],
                "target_metric": row["target_metric"],
                "metric_at_change": row["metric_at_change"],
                "outcome": row["outcome"],
                "confidence": row["confidence"],
                "side_effects": json.loads(row["side_effects"] or "[]"),
                "created_at": row["created_at"],
                "evaluated_at": row["evaluated_at"],
                "cycle_at_creation": row["cycle_at_creation"],
            })
        return results

    async def update_experiment(self, experiment_id: str, updates: dict[str, Any]) -> None:
        allowed = {"outcome", "confidence", "side_effects", "evaluated_at"}
        set_clauses = []
        params: list[Any] = []
        for key, value in updates.items():
            if key not in allowed:
                continue
            set_clauses.append(f"{key} = ?")
            if key == "side_effects":
                params.append(json.dumps(value))
            else:
                params.append(value)
        if not set_clauses:
            return
        params.append(experiment_id)
        await self._exec_write(
            f"UPDATE meta_experiments SET {', '.join(set_clauses)} WHERE id = ?",
            tuple(params),
        )

    async def get_confidence(self, param_key: str, metric_name: str) -> float:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT confidence FROM meta_confidence WHERE param_key = ? AND metric_name = ?",
            (param_key, metric_name),
        )
        row = await cursor.fetchone()
        return row["confidence"] if row else 0.5

    async def set_confidence(self, param_key: str, metric_name: str, confidence: float) -> None:
        await self._exec_write(
            """INSERT INTO meta_confidence (param_key, metric_name, confidence, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(param_key, metric_name)
               DO UPDATE SET confidence = excluded.confidence, updated_at = excluded.updated_at""",
            (param_key, metric_name, confidence, _now_iso()),
        )

    async def get_parameter_bounds(self, key: str) -> tuple[float | None, float | None]:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT min_bound, max_bound FROM parameters WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return (None, None)
        return (row["min_bound"], row["max_bound"])

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
        return int(row[0]) if row is not None else 0

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

    # ── Unified Cold Memory ─────────────────────────────────────────

    async def store_cold_memory(
        self,
        content: str,
        embedding: list[float] | None,
        entry_type: str,
        *,
        raw_content: str | None = None,
        visitor_id: str | None = None,
        weight: float = 1.0,
        category: str = "",
        metadata: dict[str, Any] | None = None,
        source_moment_id: str | None = None,
    ) -> str:
        entry_id = str(uuid.uuid4())
        await self._exec_write(
            """INSERT INTO cold_memory
               (id, content, raw_content, embedding, entry_type, visitor_id,
                weight, category, metadata, source_moment_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                content,
                raw_content,
                _serialize_embedding(embedding),
                entry_type,
                visitor_id,
                weight,
                category,
                json.dumps(metadata or {}),
                source_moment_id,
                _now_iso(),
            ),
        )
        return entry_id

    async def search_cold_memory(
        self,
        embedding: list[float],
        *,
        limit: int = 10,
        entry_type: str | None = None,
    ) -> list[dict[str, Any]]:
        conn = await self._get_db()
        if entry_type:
            cursor = await conn.execute(
                "SELECT * FROM cold_memory WHERE entry_type = ? AND embedding IS NOT NULL",
                (entry_type,),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM cold_memory WHERE embedding IS NOT NULL"
            )
        rows = await cursor.fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            stored_emb = _deserialize_embedding(row["embedding"])
            if stored_emb is None:
                continue
            cosine = _cosine_similarity(embedding, stored_emb)
            w = row["weight"] if row["weight"] is not None else 1.0
            # Blend cosine similarity with weight for ranking
            score = cosine * 0.7 + w * 0.3
            scored.append((score, {
                "id": row["id"],
                "content": row["content"],
                "raw_content": row["raw_content"],
                "entry_type": row["entry_type"],
                "visitor_id": row["visitor_id"],
                "weight": w,
                "category": row["category"],
                "metadata": json.loads(row["metadata"] or "{}"),
                "score": score,
                "cosine_score": cosine,
            }))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    # ── Totems (Semantic Facts) ────────────────────────────────────

    async def insert_totem(
        self,
        entity: str,
        *,
        visitor_id: str | None = None,
        weight: float = 0.5,
        context: str = "",
        category: str = "general",
        source_moment_id: str | None = None,
    ) -> str:
        totem_id = str(uuid.uuid4())
        now = _now_iso()
        await self._exec_write(
            """INSERT INTO totems
               (id, visitor_id, entity, weight, context, category,
                first_seen, last_referenced, source_moment_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (totem_id, visitor_id, entity, weight, context, category,
             now, now, source_moment_id),
        )
        return totem_id

    async def get_totems(
        self,
        *,
        visitor_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 10,
    ) -> list[Totem]:
        conn = await self._get_db()
        if visitor_id:
            cursor = await conn.execute(
                """SELECT * FROM totems
                   WHERE visitor_id = ? AND weight >= ?
                   ORDER BY weight DESC LIMIT ?""",
                (visitor_id, min_weight, limit),
            )
        else:
            cursor = await conn.execute(
                """SELECT * FROM totems
                   WHERE weight >= ?
                   ORDER BY weight DESC LIMIT ?""",
                (min_weight, limit),
            )
        rows = await cursor.fetchall()
        return [_row_to_totem(row) for row in rows]

    async def search_totems(self, query: str, *, limit: int = 10) -> list[Totem]:
        conn = await self._get_db()
        keywords = [kw for kw in (re.sub(r"[^\w]", "", w).lower() for w in query.split()) if len(kw) >= 2]
        if not keywords:
            return []
        # Search entity and context fields
        conditions = []
        params: list[Any] = []
        for kw in keywords:
            conditions.append("(LOWER(entity) LIKE ? OR LOWER(context) LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%"])
        where = " OR ".join(conditions)
        cursor = await conn.execute(
            f"SELECT * FROM totems WHERE {where} ORDER BY weight DESC LIMIT ?",
            (*params, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_totem(row) for row in rows]

    async def update_totem_weight(
        self, entity: str, *, visitor_id: str | None = None, weight: float
    ) -> None:
        now = _now_iso()
        if visitor_id is not None:
            await self._exec_write(
                "UPDATE totems SET weight = ?, last_referenced = ? WHERE entity = ? AND visitor_id = ?",
                (weight, now, entity, visitor_id),
            )
        else:
            await self._exec_write(
                "UPDATE totems SET weight = ?, last_referenced = ? WHERE entity = ? AND visitor_id IS NULL",
                (weight, now, entity),
            )

    # ── Visitor Traits ──────────────────────────────────────────────

    async def insert_trait(
        self,
        visitor_id: str,
        trait_category: str,
        trait_key: str,
        trait_value: str,
        *,
        confidence: float = 0.5,
        source_moment_id: str | None = None,
    ) -> str:
        trait_id = str(uuid.uuid4())
        now = _now_iso()
        await self._exec_write(
            """INSERT INTO visitor_traits
               (id, visitor_id, trait_category, trait_key, trait_value,
                confidence, source_moment_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trait_id, visitor_id, trait_category, trait_key, trait_value,
             confidence, source_moment_id, now),
        )
        return trait_id

    async def get_traits(
        self, visitor_id: str, *, category: str | None = None, limit: int = 20
    ) -> list[VisitorTrait]:
        conn = await self._get_db()
        if category:
            cursor = await conn.execute(
                """SELECT * FROM visitor_traits
                   WHERE visitor_id = ? AND trait_category = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (visitor_id, category, limit),
            )
        else:
            cursor = await conn.execute(
                """SELECT * FROM visitor_traits
                   WHERE visitor_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (visitor_id, limit),
            )
        rows = await cursor.fetchall()
        return [_row_to_trait(row) for row in rows]

    async def search_traits(self, query: str, *, limit: int = 10) -> list[VisitorTrait]:
        conn = await self._get_db()
        keywords = [kw for kw in (re.sub(r"[^\w]", "", w).lower() for w in query.split()) if len(kw) >= 2]
        if not keywords:
            return []
        conditions = []
        params: list[Any] = []
        for kw in keywords:
            conditions.append(
                "(LOWER(trait_key) LIKE ? OR LOWER(trait_value) LIKE ? OR LOWER(trait_category) LIKE ?)"
            )
            params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])
        where = " OR ".join(conditions)
        cursor = await conn.execute(
            f"SELECT * FROM visitor_traits WHERE {where} ORDER BY confidence DESC LIMIT ?",
            (*params, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_trait(row) for row in rows]

    async def get_latest_trait(
        self, visitor_id: str, category: str, key: str
    ) -> VisitorTrait | None:
        conn = await self._get_db()
        cursor = await conn.execute(
            """SELECT * FROM visitor_traits
               WHERE visitor_id = ? AND trait_category = ? AND trait_key = ?
               ORDER BY created_at DESC LIMIT 1""",
            (visitor_id, category, key),
        )
        row = await cursor.fetchone()
        return _row_to_trait(row) if row else None

    # ── Visitors ────────────────────────────────────────────────────

    async def upsert_visitor(
        self,
        visitor_id: str,
        name: str,
        *,
        emotional_imprint: str | None = None,
        summary: str | None = None,
    ) -> None:
        conn = await self._get_db()
        now = _now_iso()
        cursor = await conn.execute(
            "SELECT id FROM visitors WHERE id = ?", (visitor_id,)
        )
        existing = await cursor.fetchone()
        if existing:
            updates = ["last_visit = ?", "visit_count = visit_count + 1"]
            params: list[Any] = [now]
            if emotional_imprint is not None:
                updates.append("emotional_imprint = ?")
                params.append(emotional_imprint)
            if summary is not None:
                updates.append("summary = ?")
                params.append(summary)
            params.append(visitor_id)
            await self._exec_write(
                f"UPDATE visitors SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
        else:
            await self._exec_write(
                """INSERT INTO visitors
                   (id, name, trust_level, visit_count, first_visit, last_visit,
                    emotional_imprint, summary)
                   VALUES (?, ?, 'stranger', 1, ?, ?, ?, ?)""",
                (visitor_id, name, now, now,
                 emotional_imprint or "", summary or ""),
            )

    async def get_visitor(self, visitor_id: str) -> Visitor | None:
        conn = await self._get_db()
        cursor = await conn.execute(
            "SELECT * FROM visitors WHERE id = ?", (visitor_id,)
        )
        row = await cursor.fetchone()
        return _row_to_visitor(row) if row else None

    async def search_visitors(self, query: str, *, limit: int = 5) -> list[Visitor]:
        conn = await self._get_db()
        cursor = await conn.execute(
            """SELECT * FROM visitors
               WHERE LOWER(name) LIKE ? OR LOWER(summary) LIKE ?
               ORDER BY last_visit DESC LIMIT ?""",
            (f"%{query.lower()}%", f"%{query.lower()}%", limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_visitor(row) for row in rows]

    # ── Lifecycle ────────────────────────────────────────────────

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
            with contextlib.suppress(Exception):
                await conn.execute(sql)
        await conn.commit()

    async def initialize(self) -> None:
        conn = await self._get_db()
        for migration_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
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
        # Add new columns to self_model (idempotent ALTER TABLEs)
        await self._run_alter_columns()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None


def _row_to_totem(row: aiosqlite.Row) -> Totem:
    return Totem(
        id=row["id"],
        entity=row["entity"],
        weight=row["weight"],
        visitor_id=row["visitor_id"],
        context=row["context"],
        category=row["category"],
        first_seen=datetime.fromisoformat(row["first_seen"]) if row["first_seen"] else None,
        last_referenced=datetime.fromisoformat(row["last_referenced"]) if row["last_referenced"] else None,
        source_moment_id=row["source_moment_id"],
    )


def _row_to_trait(row: aiosqlite.Row) -> VisitorTrait:
    return VisitorTrait(
        id=row["id"],
        visitor_id=row["visitor_id"],
        trait_category=row["trait_category"],
        trait_key=row["trait_key"],
        trait_value=row["trait_value"],
        confidence=row["confidence"],
        source_moment_id=row["source_moment_id"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )


def _row_to_visitor(row: aiosqlite.Row) -> Visitor:
    return Visitor(
        id=row["id"],
        name=row["name"],
        trust_level=row["trust_level"],
        visit_count=row["visit_count"],
        first_visit=datetime.fromisoformat(row["first_visit"]) if row["first_visit"] else None,
        last_visit=datetime.fromisoformat(row["last_visit"]) if row["last_visit"] else None,
        emotional_imprint=row["emotional_imprint"],
        summary=row["summary"],
    )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
