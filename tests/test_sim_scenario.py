"""Tests for sim.scenario — ScenarioManager and ScenarioEvent."""

import pytest
from datetime import datetime, timezone, timedelta

from sim.scenario import ScenarioEvent, ScenarioManager


class TestScenarioEvent:
    def test_visitor_arrive(self):
        se = ScenarioEvent(100, "visitor_arrive", {
            "source": "tg:visitor_a", "name": "Tanaka", "channel": "telegram",
        })
        ts = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
        result = se.to_pipeline_event(ts)

        assert result["event_type"] == "visitor_connect"
        assert result["source"] == "tg:visitor_a"
        assert result["content"] == "Tanaka"
        assert result["salience"] == 0.8

    def test_visitor_message(self):
        se = ScenarioEvent(110, "visitor_message", {
            "source": "tg:visitor_a",
            "content": "Hello there!",
        })
        ts = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
        result = se.to_pipeline_event(ts)

        assert result["event_type"] == "visitor_speech"
        assert result["content"] == "Hello there!"
        assert result["salience"] == 0.9

    def test_visitor_leave(self):
        se = ScenarioEvent(149, "visitor_leave", {
            "source": "tg:visitor_a",
        })
        ts = datetime(2026, 2, 1, 11, 0, tzinfo=timezone.utc)
        result = se.to_pipeline_event(ts)

        assert result["event_type"] == "visitor_disconnect"
        assert result["salience"] == 0.6

    def test_x_mention(self):
        se = ScenarioEvent(200, "x_mention", {
            "source": "x:fan",
            "content": "@shopkeeper nice cards!",
        })
        ts = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
        result = se.to_pipeline_event(ts)

        assert result["event_type"] == "x_mention"
        assert result["source"] == "x:fan"
        assert result["content"] == "@shopkeeper nice cards!"

    def test_set_drives_meta_event(self):
        se = ScenarioEvent(0, "set_drives", {
            "mood_valence": -0.7,
            "energy": 0.3,
        })
        ts = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
        result = se.to_pipeline_event(ts)

        assert result["event_type"] == "set_drives"
        assert result["_payload"]["mood_valence"] == -0.7

    def test_event_has_id(self):
        se = ScenarioEvent(0, "visitor_arrive", {"source": "tg:x"})
        ts = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
        result = se.to_pipeline_event(ts)
        assert "id" in result
        assert len(result["id"]) > 0


class TestScenarioManager:
    def test_get_events_returns_correct_cycle(self):
        events = [
            ScenarioEvent(0, "visitor_arrive", {"source": "a"}),
            ScenarioEvent(5, "visitor_message", {"source": "a", "content": "hi"}),
            ScenarioEvent(10, "visitor_leave", {"source": "a"}),
        ]
        sm = ScenarioManager(events, name="test")

        assert len(sm.get_events(0)) == 1
        assert len(sm.get_events(1)) == 0
        assert len(sm.get_events(5)) == 1
        assert len(sm.get_events(10)) == 1

    def test_get_events_multiple_same_cycle(self):
        events = [
            ScenarioEvent(100, "visitor_arrive", {"source": "a"}),
            ScenarioEvent(100, "visitor_message", {"source": "a", "content": "hi"}),
        ]
        sm = ScenarioManager(events, name="test")
        result = sm.get_events(100)
        assert len(result) == 2

    def test_sorted_order(self):
        events = [
            ScenarioEvent(10, "visitor_leave", {"source": "a"}),
            ScenarioEvent(0, "visitor_arrive", {"source": "a"}),
            ScenarioEvent(5, "visitor_message", {"source": "a", "content": "hi"}),
        ]
        sm = ScenarioManager(events, name="test")
        assert sm.events[0].cycle == 0
        assert sm.events[1].cycle == 5
        assert sm.events[2].cycle == 10

    def test_reset(self):
        events = [
            ScenarioEvent(0, "visitor_arrive", {"source": "a"}),
            ScenarioEvent(5, "visitor_message", {"source": "a", "content": "hi"}),
        ]
        sm = ScenarioManager(events, name="test")
        sm.get_events(0)
        sm.get_events(5)

        sm.reset()
        assert len(sm.get_events(0)) == 1

    def test_total_events(self):
        events = [ScenarioEvent(i, "visitor_message", {"source": "a"}) for i in range(10)]
        sm = ScenarioManager(events, name="test")
        assert sm.total_events == 10

    def test_repr(self):
        sm = ScenarioManager([], name="test_scenario")
        assert "test_scenario" in repr(sm)

    def test_load_standard(self):
        sm = ScenarioManager.load("standard")
        assert sm.name == "standard"
        assert sm.total_events > 0

    def test_load_death_spiral(self):
        sm = ScenarioManager.load("death_spiral")
        assert sm.name == "death_spiral"
        # Should have set_drives event at cycle 0
        events = sm.get_events(0)
        assert any(e.event_type == "set_drives" for e in events)

    def test_load_isolation(self):
        sm = ScenarioManager.load("isolation")
        assert sm.name == "isolation"
        assert sm.total_events == 0

    def test_load_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            ScenarioManager.load("nonexistent")
