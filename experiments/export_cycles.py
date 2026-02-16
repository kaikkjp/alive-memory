"""Export cycle_log from a Shopkeeper SQLite DB to JSONL.

Usage:
    python -m experiments.export_cycles --db data/shopkeeper.db --out experiments/logs/run.jsonl
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """Open a read-only SQLite connection."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def parse_ts(ts_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a datetime."""
    if ts_str is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    ts_str = ts_str.strip()
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        # Fallback: try stripping trailing Z and adding UTC
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
            return datetime.fromisoformat(ts_str)
        raise


def detect_budget_rest(row: dict) -> bool:
    """Detect budget-rest cycles: token_budget=0 and routing_focus='rest'."""
    return row.get("token_budget", -1) == 0 and row.get("routing_focus") == "rest"


def detect_habit_fired(row: dict) -> bool:
    """Detect habit-fired cycles: token_budget=0 and actions non-empty."""
    actions = row.get("actions", [])
    return row.get("token_budget", -1) == 0 and len(actions) > 0


def export_row(row: sqlite3.Row, first_ts: datetime) -> dict:
    """Convert a cycle_log DB row to JSONL-ready dict."""
    ts = parse_ts(row["ts"])
    elapsed = (ts - first_ts).total_seconds() / 3600.0

    # Parse JSON fields
    drives_raw = row["drives"]
    drives = json.loads(drives_raw) if drives_raw else {}

    actions_raw = row["actions"]
    actions = json.loads(actions_raw) if actions_raw else []

    # Normalize action names: strip "action_" prefix if present
    actions = [a.replace("action_", "") if a.startswith("action_") else a for a in actions]

    monologue = row["internal_monologue"] or ""

    record = {
        "cycle_id": row["id"],
        "ts": ts.isoformat(),
        "elapsed_hours": round(elapsed, 2),
        "routing_focus": row["routing_focus"] or "idle",
        "focus_channel": row["routing_focus"] or row["mode"] or "idle",
        "actions": actions,
        "drives": {
            "social_hunger": drives.get("social_hunger", 0.0),
            "curiosity": drives.get("curiosity", 0.0),
            "expression_need": drives.get("expression_need", 0.0),
            "rest_need": drives.get("rest_need", 0.0),
            "energy": drives.get("energy", 0.0),
            "mood_valence": drives.get("mood_valence", 0.0),
            "mood_arousal": drives.get("mood_arousal", 0.0),
        },
        "token_budget": row["token_budget"] or 0,
        "internal_monologue": monologue[:100],
        "is_budget_rest": False,
        "is_habit_fired": False,
    }

    record["is_budget_rest"] = detect_budget_rest(record)
    record["is_habit_fired"] = detect_habit_fired(record)

    return record


def export_cycles(db_path: str) -> list[dict]:
    """Read all cycle_log rows and return as list of export dicts."""
    conn = connect_readonly(db_path)
    try:
        cursor = conn.execute("SELECT * FROM cycle_log ORDER BY ts ASC")
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    first_ts = parse_ts(rows[0]["ts"])
    return [export_row(row, first_ts) for row in rows]


def write_jsonl(records: list[dict], out_path: str) -> None:
    """Write records to a JSONL file."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Export cycle_log to JSONL")
    parser.add_argument("--db", required=True, help="Path to SQLite DB")
    parser.add_argument("--out", required=True, help="Output JSONL path")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"[ExportCycles] DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    records = export_cycles(args.db)
    write_jsonl(records, args.out)
    print(f"[ExportCycles] Exported {len(records)} cycles to {args.out}")


if __name__ == "__main__":
    main()
