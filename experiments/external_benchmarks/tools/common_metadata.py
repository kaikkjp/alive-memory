#!/usr/bin/env python3
"""Shared metadata + preflight helpers for external benchmark runners."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_model_name(model_name: str) -> str:
    model = (model_name or "").strip()
    if not model:
        return model
    if "/" in model:
        return model
    return f"openai/{model}"


def resolve_git_commit(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=True,
        )
        return proc.stdout.strip()
    except Exception:
        return "unknown"


def assert_expected_model(model_name: str) -> None:
    expected = os.environ.get("MODEL_EXPECTED", "").strip()
    if not expected:
        return
    current = normalize_model_name(model_name)
    if current != expected:
        raise RuntimeError(
            f"Model mismatch: MODEL_EXPECTED={expected}, runtime={current}. "
            "Refusing to run."
        )


def make_metadata(
    *,
    repo_root: Path,
    model_name: str,
    seed: int,
    run_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "model_name": normalize_model_name(model_name),
        "git_commit": resolve_git_commit(repo_root),
        "seed": seed,
        "timestamp": utc_now_iso(),
        "run_id": run_id,
    }
    if extra:
        payload.update(extra)
    return payload
