"""Tests for sim.baselines — Stateless and ReAct baselines."""

import pytest

from sim.baselines.stateless import StatelessBaseline
from sim.baselines.react_agent import ReActBaseline
from sim.clock import SimulatedClock


class TestStatelessBaseline:
    def test_never_sleeps(self):
        bl = StatelessBaseline()
        clock = SimulatedClock(start="2026-02-01T03:00:00+09:00")
        assert bl.should_sleep(clock) is False

    def test_flat_drives(self):
        bl = StatelessBaseline()
        drives = {"social_hunger": 0.9, "curiosity": 0.9,
                  "expression_need": 0.9, "rest_need": 0.9,
                  "energy": 0.1, "mood_valence": -0.9, "mood_arousal": 0.9}
        bl.pre_cycle(drives, {}, [])

        assert drives["social_hunger"] == 0.5
        assert drives["curiosity"] == 0.5
        assert drives["energy"] == 0.8
        assert drives["mood_valence"] == 0.0


class TestReActBaseline:
    def test_never_sleeps(self):
        bl = ReActBaseline()
        clock = SimulatedClock(start="2026-02-01T03:00:00+09:00")
        assert bl.should_sleep(clock) is False

    def test_flat_drives(self):
        bl = ReActBaseline()
        drives = {"social_hunger": 0.9, "curiosity": 0.9,
                  "expression_need": 0.9, "rest_need": 0.9,
                  "energy": 0.1, "mood_valence": -0.9, "mood_arousal": 0.9}
        bl.pre_cycle(drives, {}, [])

        assert drives["social_hunger"] == 0.5
        assert drives["mood_valence"] == 0.0

    def test_tracks_conversation_history(self):
        bl = ReActBaseline(history_window=5)
        events = [
            {"event_type": "visitor_speech", "content": f"msg_{i}"}
            for i in range(10)
        ]
        drives = {"social_hunger": 0.5, "curiosity": 0.5,
                  "expression_need": 0.3, "rest_need": 0.2,
                  "energy": 0.8, "mood_valence": 0.0, "mood_arousal": 0.3}

        bl.pre_cycle(drives, {}, events)
        # Only last 5 should be kept (window=5)
        assert len(bl._conversation_history) == 5
        assert bl._conversation_history[-1] == "msg_9"

    def test_ignores_non_visitor_events(self):
        bl = ReActBaseline()
        events = [
            {"event_type": "x_mention", "content": "not tracked"},
            {"event_type": "visitor_speech", "content": "tracked"},
        ]
        drives = {"social_hunger": 0.5, "curiosity": 0.5,
                  "expression_need": 0.3, "rest_need": 0.2,
                  "energy": 0.8, "mood_valence": 0.0, "mood_arousal": 0.3}

        bl.pre_cycle(drives, {}, events)
        assert len(bl._conversation_history) == 1
        assert bl._conversation_history[0] == "tracked"
