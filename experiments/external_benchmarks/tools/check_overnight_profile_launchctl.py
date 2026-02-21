#!/usr/bin/env python3
"""Check status of launchctl-based overnight benchmark profile."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def launchctl_row(label: str) -> str | None:
    proc = subprocess.run(["launchctl", "list"], text=True, capture_output=True, check=False)
    for line in (proc.stdout or "").splitlines():
        if line.strip().endswith(label):
            return line.strip()
    return None


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

    report = {"manifest": str(manifest_path), "jobs": {}}
    for name, meta in payload.get("jobs", {}).items():
        label = meta["label"]
        log_path = Path(meta["log_file"])
        report["jobs"][name] = {
            "label": label,
            "launchctl_list_row": launchctl_row(label),
            "log_file": str(log_path),
            "log_exists": log_path.exists(),
            "tail": tail_text(log_path, args.tail_lines),
        }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
