"""supervisor.registry — Pod state machine, platform DB, port allocation."""

import json
import os
import pathlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import aiosqlite


PORT_BASE = int(os.getenv("SUPERVISOR_PORT_BASE", "9001"))
PORT_MAX = int(os.getenv("SUPERVISOR_PORT_MAX", "9999"))
DEFAULT_DB_PATH = os.getenv("SUPERVISOR_DB_PATH", "data/supervisor.db")

MIGRATION_FILE = pathlib.Path(__file__).parent.parent / "migrations" / "platform_001_pods.sql"


# ---------------------------------------------------------------------------
# Pod lifecycle states
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, set[str]] = {
    "creating":   {"starting", "error", "destroying"},
    "starting":   {"running", "error", "stopping"},
    "running":    {"stopping", "error"},
    "stopping":   {"stopped", "error"},
    "stopped":    {"starting", "destroying"},
    "destroying": {"destroyed", "error"},
    "error":      {"starting", "destroying", "stopped"},
    "destroyed":  set(),  # terminal
}


# ---------------------------------------------------------------------------
# Pod dataclass
# ---------------------------------------------------------------------------

@dataclass
class Pod:
    id: str
    name: str
    state: str
    port: Optional[int]
    container_id: Optional[str]
    memory_limit_mb: int
    cpu_limit: float
    data_dir: str
    health_status: str
    health_reason: Optional[str]
    last_health_check: Optional[str]
    consecutive_failures: int
    restart_count: int
    manager_id: Optional[str]
    created_at: str
    updated_at: str
    started_at: Optional[str]
    stopped_at: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Pod":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})


class InvalidTransitionError(Exception):
    pass


class PortExhaustedError(Exception):
    pass


class PodNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class Registry:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init_db(self) -> None:
        """Open connection, enable WAL, run migration."""
        db_path = pathlib.Path(self._db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")

        migration_sql = MIGRATION_FILE.read_text()
        await self._db.executescript(migration_sql)
        await self._db.commit()
        print("[Registry] Platform DB initialized")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _utcnow(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # -- CRUD ---------------------------------------------------------------

    async def create_pod(
        self,
        pod_id: str,
        name: str,
        port: int,
        data_dir: str,
        manager_id: Optional[str] = None,
        openrouter_key_hash: str = "",
        memory_limit_mb: int = 512,
        cpu_limit: float = 0.5,
    ) -> Pod:
        now = self._utcnow()
        await self._db.execute(
            """INSERT INTO pods
               (id, name, state, port, data_dir, manager_id,
                openrouter_key_hash, memory_limit_mb, cpu_limit,
                created_at, updated_at)
               VALUES (?, ?, 'creating', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pod_id, name, port, data_dir, manager_id,
             openrouter_key_hash, memory_limit_mb, cpu_limit, now, now),
        )
        await self._db.commit()
        await self._log_event(pod_id, "created", json.dumps({"port": port}))
        return await self.get_pod(pod_id)

    async def get_pod(self, pod_id: str) -> Optional[Pod]:
        cursor = await self._db.execute("SELECT * FROM pods WHERE id = ?", (pod_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return Pod.from_row(row)

    async def list_pods(
        self,
        state: Optional[str] = None,
        manager_id: Optional[str] = None,
        exclude_destroyed: bool = True,
    ) -> list[Pod]:
        clauses = []
        params: list = []
        if state:
            clauses.append("state = ?")
            params.append(state)
        if manager_id:
            clauses.append("manager_id = ?")
            params.append(manager_id)
        if exclude_destroyed:
            clauses.append("state != 'destroyed'")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cursor = await self._db.execute(
            f"SELECT * FROM pods{where} ORDER BY created_at", params
        )
        rows = await cursor.fetchall()
        return [Pod.from_row(r) for r in rows]

    async def delete_pod(self, pod_id: str) -> None:
        """Hard-delete a destroyed pod record."""
        await self._db.execute(
            "DELETE FROM pod_events WHERE pod_id = ?", (pod_id,)
        )
        await self._db.execute("DELETE FROM pods WHERE id = ?", (pod_id,))
        await self._db.commit()

    async def adopt_pod(self, pod_id: str, target_state: str) -> Pod:
        """Force-set state for adopted pods (bypasses normal transitions)."""
        now = self._utcnow()
        await self._db.execute(
            "UPDATE pods SET state = ?, updated_at = ? WHERE id = ?",
            (target_state, now, pod_id),
        )
        await self._db.commit()
        await self._log_event(pod_id, "adopted", f"state={target_state}")
        return await self.get_pod(pod_id)

    # -- State machine ------------------------------------------------------

    async def transition(
        self, pod_id: str, new_state: str, detail: Optional[str] = None
    ) -> Pod:
        pod = await self.get_pod(pod_id)
        if pod is None:
            raise PodNotFoundError(f"Pod {pod_id} not found")

        allowed = VALID_TRANSITIONS.get(pod.state, set())
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition {pod_id} from '{pod.state}' to '{new_state}'. "
                f"Allowed: {allowed}"
            )

        now = self._utcnow()
        updates = {"state": new_state, "updated_at": now}

        if new_state == "running":
            updates["started_at"] = now
        elif new_state in ("stopped", "stopping"):
            updates["stopped_at"] = now
        elif new_state == "destroyed":
            # Free the port UNIQUE constraint so it can be reused
            updates["port"] = None

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [pod_id]
        await self._db.execute(
            f"UPDATE pods SET {set_clause} WHERE id = ?", values
        )
        await self._db.commit()
        await self._log_event(pod_id, f"state_{new_state}", detail)
        return await self.get_pod(pod_id)

    # -- Health -------------------------------------------------------------

    async def update_health(
        self,
        pod_id: str,
        status: str,
        reason: Optional[str] = None,
        consecutive_failures: Optional[int] = None,
    ) -> None:
        now = self._utcnow()
        sets = [
            "health_status = ?", "health_reason = ?",
            "last_health_check = ?", "updated_at = ?"
        ]
        params: list = [status, reason, now, now]

        if consecutive_failures is not None:
            sets.append("consecutive_failures = ?")
            params.append(consecutive_failures)

        params.append(pod_id)
        await self._db.execute(
            f"UPDATE pods SET {', '.join(sets)} WHERE id = ?", params
        )
        await self._db.commit()

    async def increment_restart_count(self, pod_id: str) -> int:
        await self._db.execute(
            "UPDATE pods SET restart_count = restart_count + 1, updated_at = ? WHERE id = ?",
            (self._utcnow(), pod_id),
        )
        await self._db.commit()
        pod = await self.get_pod(pod_id)
        return pod.restart_count if pod else 0

    async def update_container_id(self, pod_id: str, container_id: str) -> None:
        await self._db.execute(
            "UPDATE pods SET container_id = ?, updated_at = ? WHERE id = ?",
            (container_id, self._utcnow(), pod_id),
        )
        await self._db.commit()

    # -- Port allocation ----------------------------------------------------

    async def allocate_port(self) -> int:
        """Find lowest available port starting from PORT_BASE, gap-filling."""
        cursor = await self._db.execute(
            "SELECT port FROM pods WHERE state != 'destroyed' AND port IS NOT NULL ORDER BY port"
        )
        rows = await cursor.fetchall()
        used = {row["port"] for row in rows}

        port = PORT_BASE
        while port in used:
            port += 1
            if port > PORT_MAX:
                raise PortExhaustedError(
                    f"No available ports in range {PORT_BASE}-{PORT_MAX}"
                )
        return port

    # -- Events -------------------------------------------------------------

    async def get_events(self, pod_id: str, limit: int = 50) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM pod_events WHERE pod_id = ? ORDER BY id DESC LIMIT ?",
            (pod_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def _log_event(
        self, pod_id: str, event: str, detail: Optional[str] = None
    ) -> None:
        await self._db.execute(
            "INSERT INTO pod_events (pod_id, event, detail) VALUES (?, ?, ?)",
            (pod_id, event, detail),
        )
        await self._db.commit()
