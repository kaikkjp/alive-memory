"""Tests for sim.metrics.stimulus_response — N1: Stimulus-Response Coupling."""

import pytest
from sim.metrics.stimulus_response import (
    ActionProfile,
    StimulusResponseMetric,
    StimulusResponseResult,
)


class TestActionProfile:
    """Test ActionProfile.from_cycles."""

    def test_empty_cycles(self):
        p = ActionProfile.from_cycles([])
        assert p.total_cycles == 0
        assert p.idle_pct == 100.0

    def test_all_idle(self):
        cycles = [{"type": "idle", "action": None}] * 10
        p = ActionProfile.from_cycles(cycles)
        assert p.idle_pct == 100.0
        assert p.dialogue_pct == 0.0

    def test_all_dialogue(self):
        cycles = [{"type": "dialogue", "action": "speak"}] * 10
        p = ActionProfile.from_cycles(cycles)
        assert p.dialogue_pct == 100.0
        assert p.idle_pct == 0.0

    def test_mixed_actions(self):
        cycles = [
            {"type": "dialogue", "action": "speak"},
            {"type": "dialogue", "action": "speak"},
            {"type": "browse", "action": "read_content"},
            {"type": "idle", "action": "rearrange"},
            {"type": "idle", "action": None},
        ]
        p = ActionProfile.from_cycles(cycles)
        assert p.dialogue_pct == 40.0
        assert p.browse_pct == 20.0
        assert p.rearrange_pct == 20.0
        assert p.idle_pct == 20.0

    def test_sleep_excluded(self):
        cycles = [
            {"type": "dialogue", "action": "speak"},
            {"type": "sleep", "action": None},
            {"type": "sleep", "action": None},
            {"type": "idle", "action": None},
        ]
        p = ActionProfile.from_cycles(cycles)
        # Only 2 non-sleep cycles: 1 dialogue + 1 idle
        assert p.dialogue_pct == 50.0
        assert p.idle_pct == 50.0

    def test_browse_web_action(self):
        cycles = [{"type": "idle", "action": "browse_web"}]
        p = ActionProfile.from_cycles(cycles)
        assert p.browse_pct == 100.0


class TestStimulusResponseMetric:
    """Test N1 metric computation."""

    def test_basic_coupling(self):
        """Dialogue rises and rearrange falls → pass."""
        low = [
            {"type": "idle", "action": "rearrange"},
            {"type": "idle", "action": "rearrange"},
            {"type": "idle", "action": None},
            {"type": "dialogue", "action": "speak"},
        ]
        high = [
            {"type": "dialogue", "action": "speak"},
            {"type": "dialogue", "action": "speak"},
            {"type": "dialogue", "action": "speak"},
            {"type": "idle", "action": None},
        ]
        result = StimulusResponseMetric.compute(low, high)
        assert result.passed is True
        assert result.dialogue_delta > 0
        assert result.rearrange_delta < 0
        assert result.score > 0

    def test_no_coupling(self):
        """Same profile in both → no coupling."""
        cycles = [
            {"type": "idle", "action": None},
            {"type": "idle", "action": None},
        ]
        result = StimulusResponseMetric.compute(cycles, cycles)
        assert result.dialogue_delta == 0
        assert result.rearrange_delta == 0
        assert result.score == 0.0

    def test_negative_coupling(self):
        """Dialogue falls when visitors increase → fail."""
        low = [
            {"type": "dialogue", "action": "speak"},
            {"type": "dialogue", "action": "speak"},
        ]
        high = [
            {"type": "idle", "action": "rearrange"},
            {"type": "idle", "action": "rearrange"},
        ]
        result = StimulusResponseMetric.compute(low, high)
        assert result.passed is False
        assert result.dialogue_delta < 0

    def test_empty_cycles(self):
        """Empty inputs don't crash."""
        result = StimulusResponseMetric.compute([], [])
        assert result.score == 0.0

    def test_from_results(self):
        """from_results extracts cycles from result dicts."""
        low_result = {"cycles": [{"type": "idle", "action": None}] * 5}
        high_result = {"cycles": [{"type": "dialogue", "action": "speak"}] * 5}
        result = StimulusResponseMetric.from_results(low_result, high_result)
        assert result.passed is True
        assert result.dialogue_delta == 100.0

    def test_score_bounded(self):
        """Score is always in [0, 1]."""
        low = [{"type": "idle", "action": "rearrange"}] * 100
        high = [{"type": "dialogue", "action": "speak"}] * 100
        result = StimulusResponseMetric.compute(low, high)
        assert 0.0 <= result.score <= 1.0
