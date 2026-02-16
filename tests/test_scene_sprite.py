"""Tests for pipeline/scene.py — resolve_sprite_state and resolve_time_of_day.

Verifies the priority-based sprite resolution logic and JST time-of-day mapping.
"""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from models.state import DrivesState, EngagementState, RoomState
from pipeline.scene import resolve_sprite_state, resolve_time_of_day

JST = timezone(timedelta(hours=9))


# ── Fixtures ──

def _drives(energy=0.8, **kw) -> DrivesState:
    return DrivesState(energy=energy, **kw)


def _engagement(status='none', visitor_id=None) -> EngagementState:
    return EngagementState(status=status, visitor_id=visitor_id)


def _room() -> RoomState:
    return RoomState()


def _focus(p_type='internal') -> MagicMock:
    """Create a mock focus/Perception object with a given p_type."""
    f = MagicMock()
    f.p_type = p_type
    return f


# ── resolve_sprite_state tests ──

class TestSpriteStatePriority:
    """Verify priority order: surprised > tired > engaged > curious > focused > thinking."""

    def test_surprised_from_visitor_connect(self):
        """Unexpected event in recent events → surprised."""
        events = [{'event_type': 'visitor_connect'}]
        result = resolve_sprite_state(_drives(), _engagement(), _room(), events)
        assert result == 'surprised'

    def test_surprised_from_gift_received(self):
        events = [{'event_type': 'gift_received'}]
        result = resolve_sprite_state(_drives(), _engagement(), _room(), events)
        assert result == 'surprised'

    def test_surprised_beats_tired(self):
        """Surprised takes priority even with low energy."""
        events = [{'event_type': 'visitor_connect'}]
        result = resolve_sprite_state(
            _drives(energy=0.1), _engagement(), _room(), events
        )
        assert result == 'surprised'

    def test_tired_when_low_energy(self):
        """Energy < 30% → tired."""
        result = resolve_sprite_state(
            _drives(energy=0.2), _engagement(), _room(), []
        )
        assert result == 'tired'

    def test_tired_at_boundary_29(self):
        """Energy at 0.29 → tired (just below 0.30 threshold)."""
        result = resolve_sprite_state(
            _drives(energy=0.29), _engagement(), _room(), []
        )
        assert result == 'tired'

    def test_not_tired_at_30(self):
        """Energy at exactly 0.30 → NOT tired."""
        result = resolve_sprite_state(
            _drives(energy=0.30), _engagement(), _room(), []
        )
        assert result != 'tired'

    def test_tired_beats_engaged(self):
        """Tired takes priority over engaged when energy is low."""
        result = resolve_sprite_state(
            _drives(energy=0.1),
            _engagement(status='engaged', visitor_id='v1'),
            _room(),
            [],
        )
        assert result == 'tired'

    def test_engaged_with_visitor(self):
        """Has visitor AND in conversation → engaged."""
        result = resolve_sprite_state(
            _drives(),
            _engagement(status='engaged', visitor_id='v1'),
            _room(),
            [],
        )
        assert result == 'engaged'

    def test_curious_visitor_not_engaged(self):
        """Visitor present but not engaged → curious."""
        result = resolve_sprite_state(
            _drives(),
            _engagement(status='none', visitor_id='v1'),
            _room(),
            [],
        )
        assert result == 'curious'

    def test_focused_on_consume(self):
        """Consuming content (reading) → focused."""
        result = resolve_sprite_state(
            _drives(), _engagement(), _room(), [],
            focus=_focus(p_type='consume_focus'),
        )
        assert result == 'focused'

    def test_focused_on_thread(self):
        """Thread work → focused."""
        result = resolve_sprite_state(
            _drives(), _engagement(), _room(), [],
            focus=_focus(p_type='thread_focus'),
        )
        assert result == 'focused'

    def test_focused_on_news(self):
        """News reading → focused."""
        result = resolve_sprite_state(
            _drives(), _engagement(), _room(), [],
            focus=_focus(p_type='news_focus'),
        )
        assert result == 'focused'

    def test_not_focused_on_internal(self):
        """Internal/idle focus → thinking, not focused."""
        result = resolve_sprite_state(
            _drives(), _engagement(), _room(), [],
            focus=_focus(p_type='internal'),
        )
        assert result == 'thinking'

    def test_thinking_is_default(self):
        """Default idle → thinking."""
        result = resolve_sprite_state(
            _drives(), _engagement(), _room(), []
        )
        assert result == 'thinking'

    def test_thinking_when_no_focus(self):
        """Normal energy, no visitor, no focus → thinking."""
        result = resolve_sprite_state(
            _drives(energy=0.5), _engagement(), _room(), [],
            focus=None,
        )
        assert result == 'thinking'


class TestSpriteStateEdgeCases:

    def test_empty_events_no_surprise(self):
        result = resolve_sprite_state(_drives(), _engagement(), _room(), [])
        assert result != 'surprised'

    def test_non_surprise_event_ignored(self):
        """Regular events don't trigger surprised."""
        events = [{'event_type': 'timer_tick'}, {'event_type': 'cycle_complete'}]
        result = resolve_sprite_state(_drives(), _engagement(), _room(), events)
        assert result != 'surprised'

    def test_surprise_only_in_first_5_events(self):
        """Only check the first 5 recent events."""
        # 5 normal events, then a surprise at position 6
        events = [{'event_type': 'timer_tick'}] * 5 + [{'event_type': 'visitor_connect'}]
        result = resolve_sprite_state(_drives(), _engagement(), _room(), events)
        assert result != 'surprised'

    def test_engaged_requires_visitor_id(self):
        """Engaged status without visitor_id → not 'engaged' sprite."""
        result = resolve_sprite_state(
            _drives(),
            _engagement(status='engaged', visitor_id=None),
            _room(),
            [],
        )
        assert result != 'engaged'

    def test_event_without_event_type_key(self):
        """Events missing event_type key don't crash."""
        events = [{'some_other_key': 'value'}]
        result = resolve_sprite_state(_drives(), _engagement(), _room(), events)
        assert result == 'thinking'

    def test_focus_without_p_type(self):
        """Focus object without p_type attribute doesn't crash."""
        focus = MagicMock(spec=[])  # no attributes
        result = resolve_sprite_state(_drives(), _engagement(), _room(), [], focus=focus)
        assert result == 'thinking'

    def test_returns_valid_sprite_state(self):
        """Result is always one of the valid sprite states."""
        valid = {'surprised', 'tired', 'engaged', 'curious', 'focused', 'thinking'}
        focus_types = [None, _focus('internal'), _focus('consume_focus'), _focus('thread_focus')]
        for energy in [0.1, 0.3, 0.5, 0.8]:
            for status in ['none', 'engaged', 'cooldown']:
                for focus in focus_types:
                    result = resolve_sprite_state(
                        _drives(energy=energy),
                        _engagement(status=status, visitor_id='v1' if status == 'engaged' else None),
                        _room(),
                        [],
                        focus=focus,
                    )
                    assert result in valid, f"Got {result} for energy={energy}, status={status}, focus={focus}"


# ── resolve_time_of_day tests ──

class TestResolveTimeOfDay:

    def test_morning_6am(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 6, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'morning'

    def test_morning_10am(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 10, 30, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'morning'

    def test_afternoon_11am(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 11, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'afternoon'

    def test_afternoon_4pm(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 16, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'afternoon'

    def test_evening_5pm(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 17, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'evening'

    def test_evening_7pm(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 19, 30, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'evening'

    def test_night_8pm(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 20, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'night'

    def test_night_midnight(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 0, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'night'

    def test_night_3am(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 3, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'night'

    def test_night_5am(self):
        with patch('clock.now', return_value=datetime(2026, 2, 16, 5, 59, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'night'

    def test_boundary_morning_start(self):
        """6:00 AM JST is the start of morning."""
        with patch('clock.now', return_value=datetime(2026, 2, 16, 6, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'morning'

    def test_boundary_afternoon_start(self):
        """11:00 AM JST is the start of afternoon."""
        with patch('clock.now', return_value=datetime(2026, 2, 16, 11, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'afternoon'

    def test_boundary_evening_start(self):
        """5:00 PM JST is the start of evening."""
        with patch('clock.now', return_value=datetime(2026, 2, 16, 17, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'evening'

    def test_boundary_night_start(self):
        """8:00 PM JST is the start of night."""
        with patch('clock.now', return_value=datetime(2026, 2, 16, 20, 0, 0, tzinfo=JST)):
            assert resolve_time_of_day() == 'night'

    def test_returns_valid_time(self):
        """Result is always one of the valid time-of-day values."""
        valid = {'morning', 'afternoon', 'evening', 'night'}
        for hour in range(24):
            with patch('clock.now', return_value=datetime(2026, 2, 16, hour, 0, 0, tzinfo=JST)):
                result = resolve_time_of_day()
                assert result in valid, f"Got {result} for hour={hour}"
