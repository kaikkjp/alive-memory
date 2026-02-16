"""Tests for experiments.analyze_entropy — verifies Shannon entropy computation."""

import json
import math
import tempfile
from collections import Counter
from pathlib import Path

import pytest

from experiments.analyze_entropy import (
    shannon_entropy,
    load_jsonl,
    sliding_window_entropy,
    compute_block_distributions,
    extract_drive_trajectories,
    compute_summary,
    generate_figure,
)


# ─── Shannon entropy unit tests ───

def test_entropy_uniform_4():
    """Uniform distribution over 4 categories: H = log2(4) = 2.0 bits."""
    counts = Counter({"a": 25, "b": 25, "c": 25, "d": 25})
    h = shannon_entropy(counts)
    assert abs(h - 2.0) < 1e-10


def test_entropy_uniform_8():
    """Uniform distribution over 8 categories: H = log2(8) = 3.0 bits."""
    counts = Counter({f"cat{i}": 100 for i in range(8)})
    h = shannon_entropy(counts)
    assert abs(h - 3.0) < 1e-10


def test_entropy_singleton():
    """Single category: H = 0.0 bits (no uncertainty)."""
    counts = Counter({"only_one": 100})
    h = shannon_entropy(counts)
    assert h == 0.0


def test_entropy_empty():
    """Empty counter: H = 0.0 bits."""
    counts = Counter()
    h = shannon_entropy(counts)
    assert h == 0.0


def test_entropy_binary_even():
    """Two equally likely outcomes: H = 1.0 bit."""
    counts = Counter({"heads": 50, "tails": 50})
    h = shannon_entropy(counts)
    assert abs(h - 1.0) < 1e-10


def test_entropy_binary_skewed():
    """Heavily skewed binary: H < 1.0 bit."""
    counts = Counter({"common": 99, "rare": 1})
    h = shannon_entropy(counts)
    assert 0 < h < 1.0


def test_entropy_increases_with_uniformity():
    """More uniform distributions have higher entropy."""
    skewed = Counter({"a": 90, "b": 5, "c": 3, "d": 2})
    uniform = Counter({"a": 25, "b": 25, "c": 25, "d": 25})
    assert shannon_entropy(skewed) < shannon_entropy(uniform)


# ─── JSONL fixtures ───

def _make_records(focus_sequence: list[str], action_sequences: list[list[str]],
                  hours_gap: float = 2.0) -> list[dict]:
    """Build synthetic JSONL records."""
    records = []
    for i, (focus, actions) in enumerate(zip(focus_sequence, action_sequences)):
        records.append({
            "cycle_id": f"c{i:03d}",
            "ts": f"2026-02-15T{7 + int(i * hours_gap):02d}:00:00+00:00",
            "elapsed_hours": i * hours_gap,
            "routing_focus": focus,
            "focus_channel": focus,
            "actions": actions,
            "drives": {
                "social_hunger": 0.3 + (i % 5) * 0.1,
                "curiosity": 0.5,
                "expression_need": 0.4,
                "rest_need": 0.2,
                "energy": 0.8 - (i % 5) * 0.1,
                "mood_valence": 0.1,
                "mood_arousal": 0.3,
            },
            "token_budget": 3000,
            "internal_monologue": f"cycle {i}",
            "is_budget_rest": False,
            "is_habit_fired": False,
        })
    return records


@pytest.fixture
def diverse_records():
    """48 hours of diverse behavior."""
    focuses = ["idle", "express", "consume", "thread", "engage", "news", "rest", "nap",
               "idle", "express", "idle", "thread", "consume", "engage", "express", "idle",
               "news", "idle", "thread", "express", "idle", "consume", "engage", "rest"]
    actions = [
        [], ["write_journal"], [], ["write_journal", "rearrange"], ["speak"], [],
        [], ["nap"], [], ["post_x_draft"], [], ["write_journal"],
        [], ["speak"], ["write_journal"], [],
        [], [], ["rearrange"], ["write_journal"], [], [], ["speak"], [],
    ]
    return _make_records(focuses, actions)


@pytest.fixture
def monotone_records():
    """24 hours of nothing but idle."""
    return _make_records(["idle"] * 12, [[]] * 12)


@pytest.fixture
def diverse_jsonl(diverse_records, tmp_path):
    """Write diverse records to JSONL file."""
    path = str(tmp_path / "diverse.jsonl")
    with open(path, "w") as f:
        for r in diverse_records:
            f.write(json.dumps(r) + "\n")
    return path


@pytest.fixture
def baseline_jsonl(diverse_records, tmp_path):
    """Write baseline (all idle, no actions) to JSONL file."""
    path = str(tmp_path / "baseline.jsonl")
    for r in diverse_records:
        r["routing_focus"] = "idle"
        r["actions"] = []
    with open(path, "w") as f:
        for r in diverse_records:
            f.write(json.dumps(r) + "\n")
    return path


# ─── Sliding window tests ───

def test_sliding_window_produces_values(diverse_records):
    """Sliding window over diverse data produces non-zero entropies."""
    centers, entropies = sliding_window_entropy(diverse_records, "routing_focus")
    assert len(centers) > 0
    assert len(entropies) > 0
    assert all(h >= 0 for h in entropies)
    assert any(h > 0 for h in entropies)


def test_sliding_window_monotone_zero(monotone_records):
    """Monotone (all idle) has zero entropy in every window."""
    centers, entropies = sliding_window_entropy(monotone_records, "routing_focus")
    for h in entropies:
        assert h == 0.0


def test_sliding_window_diverse_higher_than_monotone(diverse_records, monotone_records):
    """Diverse records produce higher mean entropy than monotone."""
    _, h_diverse = sliding_window_entropy(diverse_records, "routing_focus")
    _, h_mono = sliding_window_entropy(monotone_records, "routing_focus")
    if h_diverse and h_mono:
        assert max(h_diverse) > max(h_mono)


# ─── Block distribution tests ───

def test_block_distributions(diverse_records):
    """Block distributions sum to total cycles per block."""
    starts, blocks = compute_block_distributions(diverse_records, block_hours=24)
    total_in_blocks = sum(sum(b.values()) for b in blocks)
    assert total_in_blocks == len(diverse_records)


# ─── Drive trajectory tests ───

def test_drive_trajectories_all_present(diverse_records):
    """All 7 drives have trajectory data."""
    trajectories = extract_drive_trajectories(diverse_records)
    assert len(trajectories) == 7
    for name, (hours, values) in trajectories.items():
        assert len(hours) == len(diverse_records)
        assert len(values) == len(diverse_records)


# ─── Summary tests ───

def test_summary_diverse(diverse_records, monotone_records):
    """Summary of diverse data shows non-zero entropy, baseline shows ~zero."""
    summary = compute_summary(diverse_records, monotone_records)
    assert summary["cycle_count"] == len(diverse_records)
    assert summary["coarse_entropy_full"] > 0
    assert summary["baseline_entropy"] == 0.0


def test_summary_action_distribution(diverse_records, monotone_records):
    """Summary action distribution includes observed actions."""
    summary = compute_summary(diverse_records, monotone_records)
    assert "write_journal" in summary["action_distribution"]


# ─── Figure generation test ───

def test_generate_figure(diverse_records, monotone_records, tmp_path):
    """Figure is generated without errors."""
    out_path = str(tmp_path / "test_figure.png")
    result = generate_figure(diverse_records, monotone_records, out_path)
    assert Path(result).exists()
    assert Path(result).stat().st_size > 0


# ─── Specific entropy value validation ───

def test_handcrafted_uniform_4_actions():
    """Hand-crafted: 100 cycles, each of 4 action types equally → H = 2.0 bits."""
    records = []
    action_types = ["write_journal", "speak", "rearrange", "post_x_draft"]
    for i in range(100):
        records.append({
            "cycle_id": f"u{i:03d}",
            "ts": f"2026-02-15T07:00:00+00:00",
            "elapsed_hours": i * 0.5,
            "routing_focus": "express",
            "actions": [action_types[i % 4]],
            "drives": {},
            "token_budget": 3000,
            "internal_monologue": "",
            "is_budget_rest": False,
            "is_habit_fired": False,
        })

    # Count actions across all records
    action_counts = Counter()
    for r in records:
        for a in r["actions"]:
            action_counts[a] += 1

    h = shannon_entropy(action_counts)
    assert abs(h - 2.0) < 1e-10, f"Expected H=2.0, got H={h}"
