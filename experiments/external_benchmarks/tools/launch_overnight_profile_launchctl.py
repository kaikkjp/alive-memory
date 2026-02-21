#!/usr/bin/env python3
"""Launch high-cost overnight benchmark profile using launchctl submit."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_job_script(path: Path, command: list[str], log_file: Path, model_expected: str) -> None:
    cmd_line = " ".join(shlex.quote(part) for part in command)
    text = "\n".join(
        [
            "#!/bin/zsh",
            f"exec >> {shlex.quote(str(log_file))} 2>&1",
            "set -e",
            "set -a",
            "source /Users/user/Documents/Tokyo-Arc/product/alive/.env",
            "set +a",
            "if [[ -z \"${OPENAI_API_KEY:-}\" && -n \"${OPENROUTER_API_KEY:-}\" ]]; then",
            "  export OPENAI_API_KEY=\"$OPENROUTER_API_KEY\"",
            "fi",
            "if [[ -z \"${OPENAI_BASE_URL:-}\" ]]; then",
            "  export OPENAI_BASE_URL=\"https://openrouter.ai/api/v1\"",
            "fi",
            f"export MODEL_EXPECTED={shlex.quote(model_expected)}",
            cmd_line,
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def submit_job(label: str, script_path: Path) -> dict[str, Any]:
    # Best-effort cleanup in case a stale label exists.
    subprocess.run(["launchctl", "remove", label], capture_output=True, text=True)

    proc = subprocess.run(
        ["launchctl", "submit", "-l", label, "--", "/bin/zsh", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "label": label,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


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
    out_dir = repo_root / "experiments" / "external_benchmarks" / "overnight_runs" / f"profile_launchctl_{run_id}"
    scripts_dir = out_dir / "scripts"
    logs_dir = out_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = {
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
        "memoryagentbench_full": [
            args.python_bin,
            str(repo_root / "experiments" / "external_benchmarks" / "tools" / "run_memoryagentbench_full.py"),
            "--force",
            "--model",
            args.model,
        ],
    }

    manifest = {
        "run_id": run_id,
        "output_dir": str(out_dir),
        "scheduler": "launchctl",
        "jobs": {},
    }

    for name, cmd in jobs.items():
        script_path = scripts_dir / f"{name}.sh"
        log_path = logs_dir / f"{name}.log"
        write_job_script(script_path, cmd, log_path, args.model)
        label = f"codex.bench.{run_id}.{name}"
        submit = submit_job(label=label, script_path=script_path)
        manifest["jobs"][name] = {
            "label": label,
            "script": str(script_path),
            "log_file": str(log_path),
            "command": cmd,
            "submit": submit,
        }

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "jobs": manifest["jobs"]}, indent=2))


if __name__ == "__main__":
    main()
