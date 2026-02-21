#!/usr/bin/env python3
"""Schedule high-cost overnight benchmark profile via `at` so jobs persist."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def schedule_with_at(script_path: Path, when: str) -> dict[str, Any]:
    cmd = f"/bin/zsh {script_path}"
    proc = subprocess.run(
        ["at", when],
        input=cmd + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    merged = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"job\s+(\d+)\s+at\s+(.+)", merged)
    if proc.returncode != 0 or not match:
        raise RuntimeError(f"Failed scheduling with at ({when}): {merged.strip()}")
    return {
        "at_job_id": int(match.group(1)),
        "at_time": match.group(2).strip(),
        "raw": merged.strip(),
    }


def write_job_script(path: Path, command: list[str], log_file: Path, model_expected: str) -> None:
    cmd_line = " ".join(shlex.quote(part) for part in command)
    text = "\n".join(
        [
            "#!/bin/zsh",
            "set -euo pipefail",
            "set -a",
            "source /Users/user/Documents/Tokyo-Arc/product/alive/.env",
            "set +a",
            f"export MODEL_EXPECTED={shlex.quote(model_expected)}",
            f"{cmd_line} >> {log_file} 2>&1",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-bin", default="/usr/local/bin/python3")
    parser.add_argument("--ultra-steps", type=int, default=50)
    parser.add_argument("--ultra-experiments", type=int, default=32)
    parser.add_argument("--ultra-concurrency", type=int, default=4)
    parser.add_argument("--maj-pairs", type=int, default=100)
    parser.add_argument("--model", default="qwen/qwen3.5-397b-a17b")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = repo_root / "experiments" / "external_benchmarks" / "overnight_runs" / f"profile_at_{run_id}"
    scripts_dir = out_dir / "scripts"
    logs_dir = out_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = {
        "maj_eval_persona_100": {
            "when": "now + 1 minute",
            "command": [
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
        },
        "clonemem_full": {
            "when": "now + 2 minutes",
            "command": [
                args.python_bin,
                str(repo_root / "experiments" / "external_benchmarks" / "tools" / "run_clonemem_full.py"),
                "--retrieve-k",
                "50",
                "--embedding-model",
                "all-MiniLM-L6-v2",
                "--num-workers",
                "1",
            ],
        },
        "ultrahorizon_heavy": {
            "when": "now + 3 minutes",
            "command": [
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
        },
        "memoryagentbench_full": {
            "when": "now + 4 minutes",
            "command": [
                args.python_bin,
                str(repo_root / "experiments" / "external_benchmarks" / "tools" / "run_memoryagentbench_full.py"),
                "--force",
                "--model",
                args.model,
            ],
        },
    }

    manifest = {
        "run_id": run_id,
        "output_dir": str(out_dir),
        "scheduler": "at",
        "jobs": {},
    }

    for name, cfg in jobs.items():
        script_path = scripts_dir / f"{name}.sh"
        log_path = logs_dir / f"{name}.log"
        write_job_script(script_path, cfg["command"], log_path, args.model)
        schedule_meta = schedule_with_at(script_path=script_path, when=cfg["when"])
        manifest["jobs"][name] = {
            "script": str(script_path),
            "log_file": str(log_path),
            "when": cfg["when"],
            "command": cfg["command"],
            **schedule_meta,
        }

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "jobs": manifest["jobs"]}, indent=2))


if __name__ == "__main__":
    main()
