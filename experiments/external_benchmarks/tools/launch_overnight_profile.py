#!/usr/bin/env python3
"""Launch high-cost overnight benchmark profile as detached background jobs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def spawn(cmd: list[str], cwd: Path, log_file: Path, env: dict[str, str]) -> dict[str, Any]:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_file.open("a", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(cwd),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
        text=True,
    )
    return {
        "pid": proc.pid,
        "cmd": cmd,
        "cwd": str(cwd),
        "log_file": str(log_file),
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-bin", default="/usr/local/bin/python3")
    parser.add_argument("--run-dir", default=None, help="Optional fixed output folder.")
    parser.add_argument("--ultra-steps", type=int, default=50)
    parser.add_argument("--ultra-experiments", type=int, default=32)
    parser.add_argument("--ultra-concurrency", type=int, default=4)
    parser.add_argument("--maj-pairs", type=int, default=100)
    parser.add_argument("--model", default="qwen/qwen3.5-397b-a17b")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (
        Path(args.run_dir).resolve()
        if args.run_dir
        else (
            repo_root
            / "experiments"
            / "external_benchmarks"
            / "overnight_runs"
            / f"profile_{run_id}"
        )
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if not env.get("OPENAI_API_KEY") and env.get("OPENROUTER_API_KEY"):
        env["OPENAI_API_KEY"] = env["OPENROUTER_API_KEY"]
    env.setdefault("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    env["MODEL_EXPECTED"] = args.model

    commands = {
        "ultrahorizon_heavy": [
            args.python_bin,
            str(repo_root / "experiments" / "external_benchmarks" / "tools" / "run_ultrahorizon_scaled.py"),
            "--steps",
            str(args.ultra_steps),
            "--n-experiments",
            str(args.ultra_experiments),
            "--max-concurrency",
            str(args.ultra_concurrency),
            "--window-size",
            "64",
            "--env",
            "seq",
            "--index",
            "overnight",
            "--exp-folder",
            "codex_overnight",
            "--model",
            args.model,
        ],
        "maj_eval_persona_100": [
            args.python_bin,
            str(repo_root / "experiments" / "external_benchmarks" / "tools" / "run_maj_eval_batch.py"),
            "--db-path",
            str(repo_root / "data" / "shopkeeper_live.db"),
            "--source-table",
            "events",
            "--max-samples",
            str(args.maj_pairs),
            "--visitor-id",
            "ALL",
            "--jury-profile",
            "persona",
            "--model",
            args.model,
            "--voting-method",
            "average",
        ],
        "memoryagentbench_full": [
            args.python_bin,
            str(repo_root / "experiments" / "external_benchmarks" / "tools" / "run_memoryagentbench_full.py"),
            "--force",
            "--model",
            args.model,
        ],
        "clonemem_full": [
            args.python_bin,
            str(repo_root / "experiments" / "external_benchmarks" / "tools" / "run_clonemem_full.py"),
            "--retrieve-k",
            "50",
            "--embedding-model",
            "all-MiniLM-L6-v2",
            "--num-workers",
            "1",
        ],
    }

    manifest = {
        "run_id": run_id,
        "started_at_utc": run_id,
        "output_dir": str(out_dir),
        "jobs": {},
    }
    for job_name, cmd in commands.items():
        job = spawn(
            cmd=cmd,
            cwd=repo_root,
            log_file=out_dir / "logs" / f"{job_name}.log",
            env=env,
        )
        manifest["jobs"][job_name] = job

    manifest_path = out_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(json.dumps({"manifest": str(manifest_path), "jobs": manifest["jobs"]}, indent=2))


if __name__ == "__main__":
    main()
