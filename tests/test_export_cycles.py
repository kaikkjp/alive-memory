"""Tests for experiments.export_cycles — verifies JSONL export from a test DB."""

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from experiments.export_cycles import export_cycles, write_jsonl, detect_budget_rest, detect_habit_fired


def _create_test_db(path: str, cycles: list[dict]) -> None:
    """Create a test SQLite DB with cycle_log table and seed data."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE cycle_log (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            drives JSON,
            focus_salience FLOAT,
            focus_type TEXT,
            routing_focus TEXT,
            token_budget INTEGER,
            memory_count INTEGER,
            internal_monologue TEXT,
            dialogue TEXT,
            expression TEXT,
            body_state TEXT,
            gaze TEXT,
            actions JSON,
            dropped JSON,
            next_cycle_hints JSON,
            ts TIMESTAMP NOT NULL
        )
    """)
    for c in cycles:
        conn.execute(
            """INSERT INTO cycle_log
               (id, mode, drives, focus_salience, focus_type, routing_focus,
                token_budget, memory_count, internal_monologue, dialogue,
                expression, body_state, gaze, actions, dropped, next_cycle_hints, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.get("id", str(uuid.uuid4())),
                c.get("mode", "express"),
                json.dumps(c.get("drives", {})),
                c.get("focus_salience", 0.5),
                c.get("focus_type", "none"),
                c.get("routing_focus", "idle"),
                c.get("token_budget", 3000),
                c.get("memory_count", 3),
                c.get("internal_monologue", "thinking..."),
                c.get("dialogue"),
                c.get("expression", "neutral"),
                c.get("body_state", "sitting"),
                c.get("gaze", "window"),
                json.dumps(c.get("actions", [])),
                json.dumps(c.get("dropped", [])),
                json.dumps(c.get("next_cycle_hints", [])),
                c["ts"],
            ),
        )
    conn.commit()
    conn.close()


def _base_ts(hour_offset: float = 0.0) -> str:
    """Generate an ISO timestamp offset by hours from a fixed start."""
    base = datetime(2026, 2, 15, 7, 0, 0, tzinfo=timezone.utc)
    dt = base + timedelta(hours=hour_offset)
    return dt.isoformat()


@pytest.fixture
def ten_cycle_db(tmp_path):
    """Create a DB with 10 known cycles spanning 48 hours."""
    db_path = str(tmp_path / "test.db")
    cycles = [
        {"id": "c01", "routing_focus": "idle", "actions": [], "token_budget": 3000,
         "drives": {"social_hunger": 0.3, "curiosity": 0.6, "expression_need": 0.4, "rest_need": 0.2, "energy": 0.8, "mood_valence": 0.1, "mood_arousal": 0.3},
         "ts": _base_ts(0)},
        {"id": "c02", "routing_focus": "express", "actions": ["write_journal"], "token_budget": 3000,
         "drives": {"social_hunger": 0.35, "curiosity": 0.55, "expression_need": 0.3, "rest_need": 0.25, "energy": 0.75, "mood_valence": 0.15, "mood_arousal": 0.35},
         "ts": _base_ts(2)},
        {"id": "c03", "routing_focus": "consume", "actions": ["action_speak"], "token_budget": 5000,
         "drives": {"social_hunger": 0.4, "curiosity": 0.7, "expression_need": 0.35, "rest_need": 0.2, "energy": 0.7, "mood_valence": 0.2, "mood_arousal": 0.4},
         "ts": _base_ts(5)},
        {"id": "c04", "routing_focus": "rest", "actions": [], "token_budget": 0,
         "drives": {"social_hunger": 0.45, "curiosity": 0.5, "expression_need": 0.3, "rest_need": 0.6, "energy": 0.3, "mood_valence": 0.0, "mood_arousal": 0.2},
         "ts": _base_ts(8)},
        {"id": "c05", "routing_focus": "thread", "actions": ["write_journal", "rearrange"], "token_budget": 5000,
         "drives": {"social_hunger": 0.5, "curiosity": 0.65, "expression_need": 0.5, "rest_need": 0.15, "energy": 0.85, "mood_valence": 0.25, "mood_arousal": 0.45},
         "ts": _base_ts(14)},
        {"id": "c06", "routing_focus": "engage", "actions": ["action_speak"], "token_budget": 5000,
         "drives": {"social_hunger": 0.2, "curiosity": 0.4, "expression_need": 0.2, "rest_need": 0.3, "energy": 0.6, "mood_valence": 0.3, "mood_arousal": 0.5},
         "ts": _base_ts(20)},
        {"id": "c07", "routing_focus": "idle", "actions": [], "token_budget": 3000,
         "drives": {"social_hunger": 0.55, "curiosity": 0.5, "expression_need": 0.45, "rest_need": 0.25, "energy": 0.7, "mood_valence": 0.05, "mood_arousal": 0.3},
         "ts": _base_ts(26)},
        {"id": "c08", "routing_focus": "news", "actions": ["write_journal"], "token_budget": 3000,
         "drives": {"social_hunger": 0.6, "curiosity": 0.75, "expression_need": 0.4, "rest_need": 0.2, "energy": 0.65, "mood_valence": 0.1, "mood_arousal": 0.35},
         "ts": _base_ts(32)},
        {"id": "c09", "routing_focus": "nap", "actions": ["action_nap"], "token_budget": 0,
         "drives": {"social_hunger": 0.5, "curiosity": 0.5, "expression_need": 0.5, "rest_need": 0.5, "energy": 0.5, "mood_valence": 0.0, "mood_arousal": 0.3},
         "ts": _base_ts(38)},
        {"id": "c10", "routing_focus": "express", "actions": ["post_x_draft"], "token_budget": 3000,
         "drives": {"social_hunger": 0.4, "curiosity": 0.6, "expression_need": 0.6, "rest_need": 0.15, "energy": 0.8, "mood_valence": 0.2, "mood_arousal": 0.4},
         "ts": _base_ts(44)},
    ]
    _create_test_db(db_path, cycles)
    return db_path


def test_export_count(ten_cycle_db):
    """Export should produce exactly 10 records."""
    records = export_cycles(ten_cycle_db)
    assert len(records) == 10


def test_export_fields_present(ten_cycle_db):
    """Each record has all required fields."""
    records = export_cycles(ten_cycle_db)
    required = {"cycle_id", "ts", "elapsed_hours", "routing_focus", "focus_channel",
                "actions", "drives", "token_budget", "internal_monologue",
                "is_budget_rest", "is_habit_fired"}
    for r in records:
        assert required.issubset(set(r.keys())), f"Missing fields: {required - set(r.keys())}"


def test_export_elapsed_hours(ten_cycle_db):
    """First record has elapsed_hours=0, subsequent are positive."""
    records = export_cycles(ten_cycle_db)
    assert records[0]["elapsed_hours"] == 0.0
    for r in records[1:]:
        assert r["elapsed_hours"] > 0


def test_export_drives_keys(ten_cycle_db):
    """Drives contain all 7 fields."""
    records = export_cycles(ten_cycle_db)
    drive_keys = {"social_hunger", "curiosity", "expression_need", "rest_need",
                  "energy", "mood_valence", "mood_arousal"}
    for r in records:
        assert set(r["drives"].keys()) == drive_keys


def test_export_budget_rest_detection(ten_cycle_db):
    """Cycle c04 (token_budget=0, routing_focus=rest) is detected as budget_rest."""
    records = export_cycles(ten_cycle_db)
    by_id = {r["cycle_id"]: r for r in records}
    assert by_id["c04"]["is_budget_rest"] is True
    assert by_id["c01"]["is_budget_rest"] is False


def test_export_habit_fired_detection(ten_cycle_db):
    """Cycle c09 (token_budget=0, actions non-empty) is detected as habit_fired."""
    records = export_cycles(ten_cycle_db)
    by_id = {r["cycle_id"]: r for r in records}
    assert by_id["c09"]["is_habit_fired"] is True
    assert by_id["c01"]["is_habit_fired"] is False


def test_export_action_prefix_stripped(ten_cycle_db):
    """action_ prefix is stripped from action names."""
    records = export_cycles(ten_cycle_db)
    by_id = {r["cycle_id"]: r for r in records}
    assert "speak" in by_id["c03"]["actions"]
    assert "action_speak" not in by_id["c03"]["actions"]


def test_write_jsonl(ten_cycle_db, tmp_path):
    """JSONL output is valid and round-trips correctly."""
    records = export_cycles(ten_cycle_db)
    out_path = str(tmp_path / "out.jsonl")
    write_jsonl(records, out_path)

    loaded = []
    with open(out_path) as f:
        for line in f:
            loaded.append(json.loads(line))

    assert len(loaded) == 10
    assert loaded[0]["cycle_id"] == "c01"


def test_empty_db(tmp_path):
    """Export from empty DB returns empty list."""
    db_path = str(tmp_path / "empty.db")
    _create_test_db(db_path, [])
    records = export_cycles(db_path)
    assert records == []


def test_monologue_truncated(tmp_path):
    """Internal monologue is truncated to 100 chars."""
    db_path = str(tmp_path / "long.db")
    long_text = "x" * 500
    _create_test_db(db_path, [
        {"id": "c_long", "internal_monologue": long_text, "ts": _base_ts(0)},
    ])
    records = export_cycles(db_path)
    assert len(records[0]["internal_monologue"]) == 100
