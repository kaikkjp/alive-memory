"""Tests for sim.variants — AblatedPipeline variants."""

import pytest

from sim.variants import AblatedPipeline, FLAT_DRIVES, NEUTRAL_AFFECT
from sim.clock import SimulatedClock


class TestAblatedPipeline:
    def test_no_drives_flattens(self):
        ap = AblatedPipeline(remove="drives")
        drives = {"social_hunger": 0.8, "curiosity": 0.9,
                  "expression_need": 0.7, "rest_need": 0.6,
                  "energy": 0.2, "mood_valence": -0.5, "mood_arousal": 0.9}
        ap.pre_cycle(drives, {}, [])
        for key, value in FLAT_DRIVES.items():
            assert drives[key] == value

    def test_no_affect_locks_mood(self):
        ap = AblatedPipeline(remove="affect")
        drives = {"mood_valence": -0.8, "mood_arousal": 0.9,
                  "social_hunger": 0.5}
        ap.pre_cycle(drives, {}, [])
        assert drives["mood_valence"] == 0.0
        assert drives["mood_arousal"] == 0.3
        assert drives["social_hunger"] == 0.5  # unchanged

    def test_no_sleep_never_sleeps(self):
        ap = AblatedPipeline(remove="sleep")
        clock = SimulatedClock(start="2026-02-01T03:00:00+09:00")  # 3AM
        assert ap.should_sleep(clock) is False

    def test_full_does_sleep(self):
        ap = AblatedPipeline(remove="drives")  # any non-sleep variant
        clock = SimulatedClock(start="2026-02-01T03:00:00+09:00")
        assert ap.should_sleep(clock) is True

    def test_non_sleep_window_no_sleep(self):
        ap = AblatedPipeline(remove="drives")
        clock = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        assert ap.should_sleep(clock) is False

    def test_no_memory_is_valid(self):
        ap = AblatedPipeline(remove="memory")
        drives = {"mood_valence": 0.0}
        # Should not crash
        ap.pre_cycle(drives, {}, [])
        assert drives["mood_valence"] == 0.0

    def test_no_basal_ganglia_is_valid(self):
        ap = AblatedPipeline(remove="basal_ganglia")
        drives = {"mood_valence": 0.0}
        ap.pre_cycle(drives, {}, [])

    def test_invalid_ablation_raises(self):
        with pytest.raises(ValueError, match="Unknown ablation"):
            AblatedPipeline(remove="consciousness")

    def test_label(self):
        ap = AblatedPipeline(remove="drives")
        assert "Drives" in ap.label
        ap2 = AblatedPipeline(remove="sleep")
        assert "Sleep" in ap2.label
