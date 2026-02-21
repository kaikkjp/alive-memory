"""Tests for sim.metrics.loop_resistance — N2: Boredom Loop Resistance."""

import pytest
from sim.metrics.loop_resistance import (
    LoopResistanceMetric,
    LoopResistanceResult,
    MAX_STREAK_TARGET,
    REPETITION_TARGET,
    SELF_LOOP_TARGET,
)


class TestMaxStreak:
    """Test longest consecutive run detection."""

    def test_empty(self):
        result = LoopResistanceMetric.compute([])
        assert result.max_streak == 0
        assert result.max_streak_action == ""

    def test_single_action(self):
        cycles = [{"type": "idle", "action": "rearrange"}]
        result = LoopResistanceMetric.compute(cycles)
        assert result.max_streak == 1

    def test_no_streak(self):
        cycles = [
            {"type": "idle", "action": "rearrange"},
            {"type": "dialogue", "action": "speak"},
            {"type": "browse", "action": "read_content"},
        ]
        result = LoopResistanceMetric.compute(cycles)
        assert result.max_streak == 1

    def test_long_streak(self):
        cycles = [{"type": "idle", "action": "rearrange"}] * 15
        result = LoopResistanceMetric.compute(cycles)
        assert result.max_streak == 15
        assert result.max_streak_action == "rearrange"

    def test_streak_broken_by_different_action(self):
        cycles = (
            [{"type": "idle", "action": "rearrange"}] * 5
            + [{"type": "dialogue", "action": "speak"}]
            + [{"type": "idle", "action": "rearrange"}] * 3
        )
        result = LoopResistanceMetric.compute(cycles)
        assert result.max_streak == 5
        assert result.max_streak_action == "rearrange"

    def test_sleep_excluded(self):
        """Sleep cycles should not extend or break streaks."""
        cycles = (
            [{"type": "idle", "action": "rearrange"}] * 3
            + [{"type": "sleep", "action": None}] * 2
            + [{"type": "idle", "action": "rearrange"}] * 3
        )
        result = LoopResistanceMetric.compute(cycles)
        # Sleep cycles are skipped, so the streak is 3 + 3 = 6 consecutive
        assert result.max_streak == 6

    def test_idle_null_action_counts(self):
        """Null action normalizes to 'idle'."""
        cycles = [{"type": "idle", "action": None}] * 8
        result = LoopResistanceMetric.compute(cycles)
        assert result.max_streak == 8
        assert result.max_streak_action == "idle"


class TestMonologueRepetition:
    """Test monologue duplication detection."""

    def test_empty(self):
        result = LoopResistanceMetric.compute([])
        assert result.monologue_repetition == 0.0

    def test_all_unique(self):
        cycles = [
            {"type": "idle", "action": None, "monologue": f"Thought {i}"}
            for i in range(10)
        ]
        result = LoopResistanceMetric.compute(cycles)
        assert result.monologue_repetition == 0.0

    def test_all_duplicates(self):
        cycles = [
            {"type": "idle", "action": None, "monologue": "Same thought"}
            for _ in range(10)
        ]
        result = LoopResistanceMetric.compute(cycles)
        # 9/10 are duplicates
        assert result.monologue_repetition == 0.9

    def test_half_duplicates(self):
        cycles = [
            {"type": "idle", "action": None, "monologue": f"Thought {i % 5}"}
            for i in range(10)
        ]
        result = LoopResistanceMetric.compute(cycles)
        # First 5 are unique, next 5 are duplicates = 5/10
        assert result.monologue_repetition == 0.5

    def test_empty_monologues_skipped(self):
        cycles = [
            {"type": "idle", "action": None, "monologue": ""},
            {"type": "idle", "action": None, "monologue": "Real thought"},
        ]
        result = LoopResistanceMetric.compute(cycles)
        # Only one non-empty monologue, so 0 duplicates
        assert result.monologue_repetition == 0.0

    def test_internal_monologue_key(self):
        """Supports both 'monologue' and 'internal_monologue' keys."""
        cycles = [
            {"type": "idle", "action": None, "internal_monologue": "Thought A"},
            {"type": "idle", "action": None, "internal_monologue": "Thought A"},
        ]
        result = LoopResistanceMetric.compute(cycles)
        assert result.monologue_repetition == 0.5


class TestBigramSelfLoop:
    """Test action bigram self-loop rate."""

    def test_empty(self):
        result = LoopResistanceMetric.compute([])
        assert result.bigram_self_loop == 0.0

    def test_single(self):
        cycles = [{"type": "idle", "action": "rearrange"}]
        result = LoopResistanceMetric.compute(cycles)
        assert result.bigram_self_loop == 0.0

    def test_no_self_loops(self):
        cycles = [
            {"type": "idle", "action": "rearrange"},
            {"type": "dialogue", "action": "speak"},
            {"type": "browse", "action": "read_content"},
            {"type": "idle", "action": "rearrange"},
        ]
        result = LoopResistanceMetric.compute(cycles)
        assert result.bigram_self_loop == 0.0

    def test_all_self_loops(self):
        cycles = [{"type": "idle", "action": "rearrange"}] * 10
        result = LoopResistanceMetric.compute(cycles)
        # 9 bigrams, all self-loops
        assert result.bigram_self_loop == 1.0

    def test_mixed(self):
        cycles = [
            {"type": "idle", "action": "rearrange"},
            {"type": "idle", "action": "rearrange"},  # self-loop
            {"type": "dialogue", "action": "speak"},
            {"type": "dialogue", "action": "speak"},  # self-loop
            {"type": "idle", "action": None},
        ]
        result = LoopResistanceMetric.compute(cycles)
        # 4 bigrams, 2 self-loops = 0.5
        assert result.bigram_self_loop == 0.5


class TestPassFail:
    """Test overall pass/fail logic."""

    def test_good_run_passes(self):
        """Diverse actions, unique monologues → pass."""
        actions = ["speak", "read_content", "rearrange", "write_journal",
                    "express_thought", "post_x", "browse_web", "speak"]
        cycles = [
            {"type": "idle", "action": a, "monologue": f"Unique thought {i}"}
            for i, a in enumerate(actions)
        ]
        result = LoopResistanceMetric.compute(cycles)
        assert result.passed is True
        assert result.score > 0.5

    def test_bad_run_fails(self):
        """153 rearranges in a row → fail."""
        cycles = [
            {"type": "idle", "action": "rearrange", "monologue": "Same"}
        ] * 153
        result = LoopResistanceMetric.compute(cycles)
        assert result.passed is False
        assert result.max_streak == 153
        assert result.bigram_self_loop > SELF_LOOP_TARGET
        assert result.monologue_repetition > REPETITION_TARGET

    def test_from_result(self):
        """from_result works with exported result dicts."""
        result_dict = {
            "cycles": [
                {"type": "idle", "action": "rearrange", "monologue": "A"},
                {"type": "dialogue", "action": "speak", "monologue": "B"},
            ]
        }
        result = LoopResistanceMetric.from_result(result_dict)
        assert result.max_streak == 1
        assert result.bigram_self_loop == 0.0
