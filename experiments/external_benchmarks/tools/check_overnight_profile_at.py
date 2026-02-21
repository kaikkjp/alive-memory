#!/usr/bin/env python3
"""Check scheduled/running status for an at-queued overnight benchmark profile."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def queued_ids() -> set[int]:
    proc = subprocess.run(["atq"], text=True, capture_output=True, check=False)
    ids: set[int] = set()
    for line in (proc.stdout or "").splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        try:
            ids.add(int(parts[0]))
        except ValueError:
            continue
    return ids


def tail_text(path: Path, max_lines: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-max_lines:]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--tail-lines", type=int, default=12)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    with manifest_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    q_ids = queued_ids()
    report = {
        "manifest": str(manifest_path),
        "queued_job_ids": sorted(q_ids),
        "jobs": {},
    }
    for name, meta in payload.get("jobs", {}).items():
        job_id = int(meta["at_job_id"])
        log_path = Path(meta["log_file"])
        report["jobs"][name] = {
            "at_job_id": job_id,
            "queued": job_id in q_ids,
            "log_file": str(log_path),
            "log_exists": log_path.exists(),
            "tail": tail_text(log_path, args.tail_lines),
        }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
