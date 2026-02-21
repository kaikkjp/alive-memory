#!/usr/bin/env python3
"""Sanity checks for observability wiring acceptance criteria."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone


def parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check observability wiring metrics.")
    parser.add_argument("--db", default="data/shopkeeper.db", help="SQLite DB path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if targets fail")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    llm_total = conn.execute("SELECT COUNT(*) AS c FROM llm_call_log").fetchone()["c"]
    llm_missing_cycle = conn.execute(
        "SELECT COUNT(*) AS c FROM llm_call_log WHERE COALESCE(cycle_id, '') = ''"
    ).fetchone()["c"]
    llm_missing_rate = (llm_missing_cycle / llm_total) if llm_total else 0.0

    action_total = conn.execute("SELECT COUNT(*) AS c FROM action_log").fetchone()["c"]
    action_missing_cycle = conn.execute(
        "SELECT COUNT(*) AS c FROM action_log WHERE COALESCE(cycle_id, '') = ''"
    ).fetchone()["c"]
    action_missing_rate = (action_missing_cycle / action_total) if action_total else 0.0

    run_meta = {}
    if table_exists(conn, "run_registry"):
        row = conn.execute(
            """SELECT run_id, commit_hash, config_hash, model_name, seed,
                      started_at_utc, ended_at_utc, status
               FROM run_registry
               ORDER BY started_at_utc DESC
               LIMIT 1"""
        ).fetchone()
        if row:
            run_meta = dict(row)

    recall = {
        "injections": 0,
        "tests_ge_6h": 0,
        "tests_ge_24h": 0,
    }
    if table_exists(conn, "recall_injection_log") and table_exists(conn, "recall_test_log"):
        recall["injections"] = conn.execute(
            "SELECT COUNT(*) AS c FROM recall_injection_log"
        ).fetchone()["c"]
        tests = conn.execute(
            """SELECT t.test_time_utc, t.horizon_hours, t.fact_id,
                      i.injection_time_utc
               FROM recall_test_log t
               LEFT JOIN recall_injection_log i
                 ON i.fact_id = t.fact_id AND i.run_id = t.run_id"""
        ).fetchall()
        ge_6 = 0
        ge_24 = 0
        for row in tests:
            horizon = row["horizon_hours"]
            if horizon is None:
                inj = parse_ts(row["injection_time_utc"])
                tst = parse_ts(row["test_time_utc"])
                if inj and tst:
                    horizon = int((tst - inj).total_seconds() // 3600)
            if horizon is None:
                continue
            if horizon >= 6:
                ge_6 += 1
            if horizon >= 24:
                ge_24 += 1
        recall["tests_ge_6h"] = ge_6
        recall["tests_ge_24h"] = ge_24

    summary = {
        "llm": {
            "total": llm_total,
            "missing_cycle_id": llm_missing_cycle,
            "missing_cycle_id_rate": round(llm_missing_rate, 6),
            "target_rate_max": 0.05,
            "passes": llm_missing_rate < 0.05,
        },
        "actions": {
            "total": action_total,
            "missing_cycle_id": action_missing_cycle,
            "missing_cycle_id_rate": round(action_missing_rate, 6),
            "target_rate_max": 0.0,
            "passes": action_missing_rate == 0.0,
        },
        "run_metadata": {
            "present": bool(run_meta),
            "run_id": run_meta.get("run_id", ""),
            "commit_hash": run_meta.get("commit_hash", ""),
            "config_hash": run_meta.get("config_hash", ""),
        },
        "recall_dataset": {
            **recall,
            "target_injections_min": 50,
            "target_tests_ge_6h_min": 40,
            "target_tests_ge_24h_min": 40,
            "passes": (
                recall["injections"] >= 50
                and recall["tests_ge_6h"] >= 40
                and recall["tests_ge_24h"] >= 40
            ),
        },
    }

    print(json.dumps(summary, indent=2, ensure_ascii=True))

    if not args.strict:
        return 0

    ok = (
        summary["llm"]["passes"]
        and summary["actions"]["passes"]
        and bool(summary["run_metadata"]["run_id"])
        and bool(summary["run_metadata"]["commit_hash"])
        and bool(summary["run_metadata"]["config_hash"])
        and summary["recall_dataset"]["passes"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
