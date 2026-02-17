"""Tests for window_state.py — thread wiring and scene state in broadcast payloads.

Verifies that db.get_active_threads() data appears in both
build_initial_state() and build_cycle_broadcast() payloads.
Also verifies sprite_state and time_of_day fields in broadcasts.
"""

import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Mock db and pipeline.scene before importing window_state ──
# IMPORTANT: Do NOT mock the top-level "pipeline" package — that breaks
# test_validator / test_sanitize / test_hypothalamus which import real
# pipeline submodules.  Only mock the leaf module "pipeline.scene" and "db".

_mock_db = MagicMock()
sys.modules["db"] = _mock_db


# Mock SceneLayers returned by build_scene_layers
@dataclass
class _FakeLayers:
    def to_dict(self):
        return {'background': 'bg', 'shop': 'shop', 'items': [],
                'character': 'char', 'character_position': {'x': 0, 'y': 0, 'width': 64, 'height': 128},
                'foreground': [], 'weather': 'clear', 'scene_id': 'test'}


_mock_scene = MagicMock()
_mock_scene.build_scene_layers = AsyncMock(return_value=_FakeLayers())
_mock_scene.get_time_of_day = MagicMock(return_value='morning')
_mock_scene.resolve_sprite_state = MagicMock(return_value='thinking')
_mock_scene.resolve_time_of_day = MagicMock(return_value='afternoon')
sys.modules["pipeline.scene"] = _mock_scene

from models.state import DrivesState, RoomState, EngagementState, Thread
import window_state


# ── Fixtures ──

def _make_threads():
    """Create sample Thread objects matching db.get_active_threads output."""
    return [
        Thread(
            id='t-001',
            thread_type='question',
            title='Why do old books smell sweet?',
            status='active',
            priority=0.8,
        ),
        Thread(
            id='t-002',
            thread_type='project',
            title='Rearranging the poetry shelf',
            status='open',
            priority=0.5,
        ),
    ]


def _make_drives():
    return DrivesState(
        social_hunger=0.5, curiosity=0.5, expression_need=0.3,
        rest_need=0.2, energy=0.8, mood_valence=0.0, mood_arousal=0.3,
    )


def _make_room():
    return RoomState(weather='clear', shop_status='open')


def _make_engagement():
    return EngagementState(status='none')


def _setup_db_mocks(threads=None):
    """Configure db mock to return standard test data."""
    _mock_db.get_drives_state = AsyncMock(return_value=_make_drives())
    _mock_db.get_room_state = AsyncMock(return_value=_make_room())
    _mock_db.get_engagement_state = AsyncMock(return_value=_make_engagement())
    _mock_db.get_recent_text_fragments = AsyncMock(return_value=[])
    _mock_db.get_shelf_assignments = AsyncMock(return_value=[])
    _mock_db.get_active_threads = AsyncMock(return_value=threads or [])
    _mock_db.get_recent_events = AsyncMock(return_value=[])
    _mock_db.get_budget_remaining = AsyncMock(return_value={'budget': 5.0, 'spent': 0, 'remaining': 5.0})


# ── Tests ──

@pytest.mark.asyncio
async def test_initial_state_contains_threads():
    """build_initial_state includes serialized threads in state.threads."""
    threads = _make_threads()
    _setup_db_mocks(threads=threads)

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc)
    )

    state_threads = result['state']['threads']
    assert len(state_threads) == 2
    assert state_threads[0]['id'] == 't-001'
    assert state_threads[0]['title'] == 'Why do old books smell sweet?'
    assert state_threads[0]['status'] == 'active'
    assert state_threads[0]['thread_type'] == 'question'
    assert state_threads[0]['tags'] == []
    assert state_threads[0]['touch_count'] == 0
    assert state_threads[1]['id'] == 't-002'
    assert state_threads[1]['title'] == 'Rearranging the poetry shelf'
    assert state_threads[1]['status'] == 'open'


@pytest.mark.asyncio
async def test_initial_state_empty_threads():
    """build_initial_state returns empty list when no threads exist."""
    _setup_db_mocks(threads=[])

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc)
    )

    assert result['state']['threads'] == []


@pytest.mark.asyncio
async def test_cycle_broadcast_contains_threads():
    """build_cycle_broadcast includes serialized threads in state.threads."""
    threads = _make_threads()
    _setup_db_mocks(threads=threads)

    result = await window_state.build_cycle_broadcast(
        cycle_log={'routing_focus': 'idle'},
        drives=_make_drives(),
        ambient={'condition': 'clear', 'diegetic': 'Clear skies outside.'},
        focus=None,
        engagement=_make_engagement(),
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc),
    )

    state_threads = result['state']['threads']
    assert len(state_threads) == 2
    assert state_threads[0]['id'] == 't-001'
    assert state_threads[0]['title'] == 'Why do old books smell sweet?'
    assert state_threads[0]['status'] == 'active'


@pytest.mark.asyncio
async def test_cycle_broadcast_empty_threads():
    """build_cycle_broadcast returns empty list when no threads exist."""
    _setup_db_mocks(threads=[])

    result = await window_state.build_cycle_broadcast(
        cycle_log={'routing_focus': 'idle'},
        drives=_make_drives(),
        ambient={'condition': 'clear', 'diegetic': ''},
        focus=None,
        engagement=_make_engagement(),
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert result['state']['threads'] == []


@pytest.mark.asyncio
async def test_thread_serialization_includes_expected_fields():
    """Serialized threads contain id, title, status, thread_type, tags, touch_count, last_touched."""
    threads = _make_threads()
    _setup_db_mocks(threads=threads)

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc)
    )

    expected_keys = {'id', 'title', 'status', 'thread_type', 'tags', 'touch_count', 'last_touched'}
    for t in result['state']['threads']:
        assert set(t.keys()) == expected_keys


# ── Scene compositor field tests ──

VALID_SPRITE_STATES = {'surprised', 'tired', 'engaged', 'curious', 'focused', 'thinking'}
VALID_TIME_OF_DAY = {'morning', 'afternoon', 'evening', 'night'}


@pytest.mark.asyncio
async def test_initial_state_contains_sprite_state():
    """build_initial_state includes sprite_state in state."""
    _setup_db_mocks()
    _mock_scene.resolve_sprite_state.return_value = 'thinking'

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc)
    )

    assert 'sprite_state' in result['state']
    assert result['state']['sprite_state'] in VALID_SPRITE_STATES


@pytest.mark.asyncio
async def test_initial_state_contains_time_of_day():
    """build_initial_state includes time_of_day in state."""
    _setup_db_mocks()
    _mock_scene.resolve_time_of_day.return_value = 'afternoon'

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc)
    )

    assert 'time_of_day' in result['state']
    assert result['state']['time_of_day'] in VALID_TIME_OF_DAY


@pytest.mark.asyncio
async def test_cycle_broadcast_contains_sprite_state():
    """build_cycle_broadcast includes sprite_state in state."""
    _setup_db_mocks()
    _mock_scene.resolve_sprite_state.return_value = 'engaged'

    result = await window_state.build_cycle_broadcast(
        cycle_log={'routing_focus': 'idle'},
        drives=_make_drives(),
        ambient={'condition': 'clear', 'diegetic': ''},
        focus=None,
        engagement=_make_engagement(),
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert 'sprite_state' in result['state']
    assert result['state']['sprite_state'] in VALID_SPRITE_STATES


@pytest.mark.asyncio
async def test_cycle_broadcast_contains_time_of_day():
    """build_cycle_broadcast includes time_of_day in state."""
    _setup_db_mocks()
    _mock_scene.resolve_time_of_day.return_value = 'evening'

    result = await window_state.build_cycle_broadcast(
        cycle_log={'routing_focus': 'idle'},
        drives=_make_drives(),
        ambient={'condition': 'clear', 'diegetic': ''},
        focus=None,
        engagement=_make_engagement(),
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert 'time_of_day' in result['state']
    assert result['state']['time_of_day'] in VALID_TIME_OF_DAY


@pytest.mark.asyncio
async def test_sprite_state_value_matches_resolver():
    """sprite_state value comes from resolve_sprite_state."""
    _setup_db_mocks()
    _mock_scene.resolve_sprite_state.return_value = 'surprised'

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc)
    )

    assert result['state']['sprite_state'] == 'surprised'


@pytest.mark.asyncio
async def test_time_of_day_value_matches_resolver():
    """time_of_day value comes from resolve_time_of_day."""
    _setup_db_mocks()
    _mock_scene.resolve_time_of_day.return_value = 'night'

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 14, 10, 0, 0, tzinfo=timezone.utc)
    )

    assert result['state']['time_of_day'] == 'night'
