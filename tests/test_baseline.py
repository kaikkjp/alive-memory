"""Tests for experiments.generate_baseline — verifies all baseline records are idle."""

import json
import tempfile
from pathlib import Path

import pytest

from experiments.generate_baseline import generate_baseline, write_jsonl


@pytest.fixture
def sample_source(tmp_path):
    """Create a sample source JSONL with varied routing_focus values."""
    records = [
        {"cycle_id": "c1", "ts": "2026-02-15T07:00:00+00:00", "elapsed_hours": 0.0,
         "routing_focus": "express", "focus_channel": "express",
         "actions": ["write_journal"], "drives": {"social_hunger": 0.3},
         "token_budget": 3000, "internal_monologue": "...",
         "is_budget_rest": False, "is_habit_fired": False},
        {"cycle_id": "c2", "ts": "2026-02-15T09:00:00+00:00", "elapsed_hours": 2.0,
         "routing_focus": "engage", "focus_channel": "engage",
         "actions": ["action_speak"], "drives": {"social_hunger": 0.2},
         "token_budget": 5000, "internal_monologue": "...",
         "is_budget_rest": False, "is_habit_fired": False},
        {"cycle_id": "c3", "ts": "2026-02-15T12:00:00+00:00", "elapsed_hours": 5.0,
         "routing_focus": "consume", "focus_channel": "consume",
         "actions": [], "drives": {"social_hunger": 0.5},
         "token_budget": 3000, "internal_monologue": "...",
         "is_budget_rest": False, "is_habit_fired": False},
        {"cycle_id": "c4", "ts": "2026-02-15T15:00:00+00:00", "elapsed_hours": 8.0,
         "routing_focus": "rest", "focus_channel": "rest",
         "actions": [], "drives": {"social_hunger": 0.6},
         "token_budget": 0, "internal_monologue": "",
         "is_budget_rest": True, "is_habit_fired": False},
    ]
    path = str(tmp_path / "source.jsonl")
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def test_baseline_all_idle(sample_source):
    """All baseline records have routing_focus='idle'."""
    records = generate_baseline(sample_source)
    for r in records:
        assert r["routing_focus"] == "idle"
        assert r["focus_channel"] == "idle"


def test_baseline_all_empty_actions(sample_source):
    """All baseline records have empty actions."""
    records = generate_baseline(sample_source)
    for r in records:
        assert r["actions"] == []


def test_baseline_preserves_timestamps(sample_source):
    """Baseline preserves cycle_id, ts, and elapsed_hours from source."""
    records = generate_baseline(sample_source)
    assert len(records) == 4
    assert records[0]["cycle_id"] == "c1"
    assert records[0]["ts"] == "2026-02-15T07:00:00+00:00"
    assert records[0]["elapsed_hours"] == 0.0
    assert records[2]["cycle_id"] == "c3"
    assert records[2]["elapsed_hours"] == 5.0


def test_baseline_count_matches_source(sample_source):
    """Baseline has same number of records as source."""
    records = generate_baseline(sample_source)
    with open(sample_source) as f:
        source_count = sum(1 for line in f if line.strip())
    assert len(records) == source_count


def test_baseline_no_budget_rest(sample_source):
    """Baseline records never have is_budget_rest=True."""
    records = generate_baseline(sample_source)
    for r in records:
        assert r["is_budget_rest"] is False


def test_baseline_no_habit_fired(sample_source):
    """Baseline records never have is_habit_fired=True."""
    records = generate_baseline(sample_source)
    for r in records:
        assert r["is_habit_fired"] is False


def test_baseline_write_jsonl(sample_source, tmp_path):
    """Baseline JSONL is valid and round-trips."""
    records = generate_baseline(sample_source)
    out_path = str(tmp_path / "baseline.jsonl")
    write_jsonl(records, out_path)

    loaded = []
    with open(out_path) as f:
        for line in f:
            loaded.append(json.loads(line))

    assert len(loaded) == 4
    for r in loaded:
        assert r["routing_focus"] == "idle"
        assert r["actions"] == []
