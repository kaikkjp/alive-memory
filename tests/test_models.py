"""Tests for models — Event, DrivesState, EngagementState."""

from datetime import datetime, timezone

from models.event import Event
from models.state import DrivesState, EngagementState, RoomState


class TestEvent:
    """Event dataclass creation and defaults."""

    def test_create_event(self):
        e = Event(event_type='visitor_speech', source='visitor:abc', payload={'text': 'hi'})
        assert e.event_type == 'visitor_speech'
        assert e.source == 'visitor:abc'
        assert e.payload == {'text': 'hi'}

    def test_auto_id(self):
        e = Event(event_type='ambient', source='system', payload={})
        assert e.id is not None
        assert len(e.id) > 0

    def test_unique_ids(self):
        e1 = Event(event_type='ambient', source='system', payload={})
        e2 = Event(event_type='ambient', source='system', payload={})
        assert e1.id != e2.id

    def test_auto_timestamp(self):
        e = Event(event_type='ambient', source='system', payload={})
        assert isinstance(e.ts, datetime)
        assert e.ts.tzinfo is not None


class TestDrivesState:
    """DrivesState dataclass and copy behavior."""

    def test_defaults(self):
        d = DrivesState()
        assert d.energy == 0.8
        assert d.social_hunger == 0.5

    def test_copy_is_independent(self):
        d = DrivesState(energy=0.5)
        d2 = d.copy()
        d2.energy = 0.9
        assert d.energy == 0.5  # original unchanged

    def test_copy_preserves_values(self):
        d = DrivesState(energy=0.3, mood_valence=-0.5, curiosity=0.9)
        d2 = d.copy()
        assert d2.energy == 0.3
        assert d2.mood_valence == -0.5
        assert d2.curiosity == 0.9


class TestEngagementState:
    """EngagementState — is_engaged_with visitor matching."""

    def test_not_engaged(self):
        e = EngagementState(status='none')
        assert not e.is_engaged_with('visitor:abc')

    def test_engaged_with_matching_visitor(self):
        e = EngagementState(status='engaged', visitor_id='abc')
        assert e.is_engaged_with('visitor:abc')

    def test_engaged_with_different_visitor(self):
        e = EngagementState(status='engaged', visitor_id='abc')
        assert not e.is_engaged_with('visitor:xyz')

    def test_bare_id_matching(self):
        e = EngagementState(status='engaged', visitor_id='abc')
        assert e.is_engaged_with('abc')


class TestRoomState:
    """RoomState defaults."""

    def test_defaults(self):
        r = RoomState()
        assert r.time_of_day == 'morning'
        assert r.weather == 'clear'
        assert r.shop_status == 'open'
