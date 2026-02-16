"""Generate a null-hypothesis baseline JSONL from an exported isolation run.

Reads timestamps only from the source, outputs matching records where
routing_focus is always "idle" and actions is always empty. This represents
a system that does nothing — the lower bound for behavioral entropy.

Usage:
    python -m experiments.generate_baseline --source experiments/logs/run.jsonl --out experiments/logs/baseline.jsonl
"""

import argparse
import json
import sys
from pathlib import Path


def generate_baseline(source_path: str) -> list[dict]:
    """Read source JSONL, produce baseline records with idle focus and no actions."""
    records = []
    with open(source_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            src = json.loads(line)
            baseline = {
                "cycle_id": src["cycle_id"],
                "ts": src["ts"],
                "elapsed_hours": src["elapsed_hours"],
                "routing_focus": "idle",
                "focus_channel": "idle",
                "actions": [],
                "drives": {
                    "social_hunger": 0.5,
                    "curiosity": 0.5,
                    "expression_need": 0.5,
                    "rest_need": 0.5,
                    "energy": 0.5,
                    "mood_valence": 0.0,
                    "mood_arousal": 0.5,
                },
                "token_budget": 0,
                "internal_monologue": "",
                "is_budget_rest": False,
                "is_habit_fired": False,
            }
            records.append(baseline)
    return records


def write_jsonl(records: list[dict], out_path: str) -> None:
    """Write records to a JSONL file."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Generate null-hypothesis baseline JSONL")
    parser.add_argument("--source", required=True, help="Source JSONL from export_cycles")
    parser.add_argument("--out", required=True, help="Output baseline JSONL path")
    args = parser.parse_args()

    if not Path(args.source).exists():
        print(f"[Baseline] Source not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    records = generate_baseline(args.source)
    write_jsonl(records, args.out)
    print(f"[Baseline] Generated {len(records)} baseline records to {args.out}")


if __name__ == "__main__":
    main()
