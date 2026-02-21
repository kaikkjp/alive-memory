"""Runtime observability context.

Provides:
- Process-level run metadata (`run_id`, `commit_hash`, `config_hash`)
- Cycle-scoped context propagation via contextvars
- Small hashing helpers for privacy-preserving log fields
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import pathlib
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import clock


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_text(value: str | None) -> str:
    """Hash arbitrary text with SHA-256 (hex)."""
    if not value:
        return ""
    return _sha256_hex(value)


def hash_json(value: Any) -> str:
    """Hash JSON-serializable data deterministically."""
    try:
        payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except Exception:
        payload = str(value)
    return _sha256_hex(payload)


def _git_commit_hash() -> str:
    env_hash = (os.getenv("GIT_COMMIT_HASH") or "").strip()
    if env_hash:
        return env_hash
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(pathlib.Path(__file__).resolve().parent),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out
    except Exception:
        return "unknown"


def _file_hash(path: pathlib.Path) -> str:
    try:
        return _sha256_hex(path.read_text(encoding="utf-8"))
    except Exception:
        return ""


def _default_config_hash() -> str:
    repo = pathlib.Path(__file__).resolve().parent
    payload = {
        "db_path": os.getenv("SHOPKEEPER_DB_PATH", "data/shopkeeper.db"),
        "model_expected": os.getenv("MODEL_EXPECTED", ""),
        "cortex_model": os.getenv("CORTEX_MODEL", ""),
        "reflect_model": os.getenv("REFLECT_MODEL", ""),
        "budget_cfg_sha": _file_hash(repo / "prompt" / "budget_config.json"),
        "self_context_sha": _file_hash(repo / "prompt" / "self_context.py"),
    }
    return hash_json(payload)


@dataclass
class RunMetadata:
    run_id: str
    boot_cycle_id: str
    commit_hash: str
    config_hash: str
    process_start_utc: str


@dataclass
class CycleContext:
    cycle_id: str
    run_id: str
    mode: str
    focus: str
    budget_state: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""


_run_id = (os.getenv("ALIVE_RUN_ID") or str(uuid.uuid4())).strip()
_boot_cycle_id = f"boot-{_run_id[:8]}"
_run_meta = RunMetadata(
    run_id=_run_id,
    boot_cycle_id=_boot_cycle_id,
    commit_hash=(os.getenv("GIT_COMMIT_HASH") or "").strip(),
    config_hash=(os.getenv("CONFIG_HASH") or _default_config_hash()).strip(),
    process_start_utc=clock.now_utc().isoformat(),
)

_cycle_ctx_var: contextvars.ContextVar[Optional[CycleContext]] = contextvars.ContextVar(
    "cycle_context",
    default=None,
)


def get_run_metadata() -> RunMetadata:
    if not _run_meta.commit_hash:
        _run_meta.commit_hash = _git_commit_hash()
    return _run_meta


def get_run_id() -> str:
    return _run_meta.run_id


def get_boot_cycle_id() -> str:
    return _run_meta.boot_cycle_id


def get_cycle_context() -> Optional[CycleContext]:
    return _cycle_ctx_var.get()


def set_cycle_context(ctx: CycleContext) -> contextvars.Token:
    return _cycle_ctx_var.set(ctx)


def reset_cycle_context(token: contextvars.Token) -> None:
    _cycle_ctx_var.reset(token)


def clear_cycle_context() -> None:
    _cycle_ctx_var.set(None)


def resolve_cycle_id(explicit_cycle_id: str | None = None) -> str | None:
    if explicit_cycle_id:
        return explicit_cycle_id
    ctx = get_cycle_context()
    return ctx.cycle_id if ctx else None


def resolve_run_id(explicit_run_id: str | None = None) -> str:
    if explicit_run_id:
        return explicit_run_id
    ctx = get_cycle_context()
    if ctx and ctx.run_id:
        return ctx.run_id
    return _run_meta.run_id


def resolve_trace_id(explicit_trace_id: str | None = None) -> str:
    if explicit_trace_id:
        return explicit_trace_id
    ctx = get_cycle_context()
    return ctx.trace_id if ctx else ""
