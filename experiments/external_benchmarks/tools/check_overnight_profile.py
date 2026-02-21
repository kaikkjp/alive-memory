#!/usr/bin/env python3
"""Check status of overnight benchmark jobs launched by launch_overnight_profile.py."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def tail_text(path: Path, max_lines: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-max_lines:]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to overnight manifest.json")
    parser.add_argument("--tail-lines", type=int, default=8)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    with manifest_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    jobs = payload.get("jobs", {})
    report = {"manifest": str(manifest_path), "jobs": {}}
    for name, meta in jobs.items():
        pid = int(meta["pid"])
        log_path = Path(meta["log_file"])
        report["jobs"][name] = {
            "pid": pid,
            "alive": is_alive(pid),
            "log_file": str(log_path),
            "tail": tail_text(log_path, args.tail_lines),
        }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
