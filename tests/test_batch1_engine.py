"""Tests for TASK-095 v3.1 Batch 1: Engine Foundation.

Tests organism param computation, inner voice DB query,
agent feeds CRUD, manager drops, and window state lounge fields.
"""

import math
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Organism param tests (pure function, no mocking needed) ──

from api.organism import compute_organism_params


class TestOrganismParams:
    """Test compute_organism_params for all state combinations."""

    def _default_drives(self):
        return {'curiosity': 0.5, 'social_hunger': 0.4, 'expression_need': 0.7}

    def test_sleeping_speed(self):
        result = compute_organism_params(
            self._default_drives(), 0.5, 0.3, 0.8,
            is_sleeping=True, is_dreaming=False, is_thinking=False,
        )
        assert result['evolution_speed'] == pytest.approx(math.pi / 120)

    def test_thinking_speed(self):
        result = compute_organism_params(
            self._default_drives(), 0.5, 0.3, 0.8,
            is_sleeping=False, is_dreaming=False, is_thinking=True,
        )
        assert result['evolution_speed'] == pytest.approx(math.pi / 40)

    def test_aroused_speed(self):
        result = compute_organism_params(
            self._default_drives(), 0.5, 0.7, 0.8,
            is_sleeping=False, is_dreaming=False, is_thinking=False,
        )
        assert result['evolution_speed'] == pytest.approx(math.pi / 35)

    def test_default_speed(self):
        result = compute_organism_params(
            self._default_drives(), 0.5, 0.3, 0.8,
            is_sleeping=False, is_dreaming=False, is_thinking=False,
        )
        assert result['evolution_speed'] == pytest.approx(math.pi / 45)

    def test_complexity_range(self):
        low = compute_organism_params(
            {'curiosity': 1.0, 'social_hunger': 0.5, 'expression_need': 0.5},
            0.5, 0.3, 0.8, False, False, False,
        )
        high = compute_organism_params(
            {'curiosity': 0.0, 'social_hunger': 0.5, 'expression_need': 0.5},
            0.5, 0.3, 0.8, False, False, False,
        )
        assert low['complexity'] == pytest.approx(4.0)
        assert high['complexity'] == pytest.approx(8.0)

    def test_stroke_alpha_range(self):
        low = compute_organism_params(
            self._default_drives(), 0.5, 0.3, 0.0, False, False, False,
        )
        high = compute_organism_params(
            self._default_drives(), 0.5, 0.3, 1.0, False, False, False,
        )
        assert low['stroke_alpha'] == pytest.approx(40.0)
        assert high['stroke_alpha'] == pytest.approx(120.0)

    def test_amplitude_range(self):
        low = compute_organism_params(
            {'curiosity': 0.5, 'social_hunger': 0.0, 'expression_need': 0.5},
            0.5, 0.3, 0.8, False, False, False,
        )
        high = compute_organism_params(
            {'curiosity': 0.5, 'social_hunger': 1.0, 'expression_need': 0.5},
            0.5, 0.3, 0.8, False, False, False,
        )
        assert low['amplitude'] == pytest.approx(0.7)
        assert high['amplitude'] == pytest.approx(1.3)

    def test_phase_offsets(self):
        drives = {'curiosity': 0.6, 'social_hunger': 0.4, 'expression_need': 0.7}
        result = compute_organism_params(drives, 0.5, 0.3, 0.8, False, False, False)
        assert result['phase_offsets'] == [0.6, 0.4, 0.7]

    def test_dream_flare_passthrough(self):
        result = compute_organism_params(
            self._default_drives(), 0.5, 0.3, 0.8,
            is_sleeping=True, is_dreaming=True, is_thinking=False,
        )
        assert result['dream_flare'] is True

    def test_thinking_boost_passthrough(self):
        result = compute_organism_params(
            self._default_drives(), 0.5, 0.3, 0.8,
            is_sleeping=False, is_dreaming=False, is_thinking=True,
        )
        assert result['thinking_boost'] is True

    def test_sleep_overrides_thinking(self):
        """Sleep takes priority over thinking for speed."""
        result = compute_organism_params(
            self._default_drives(), 0.5, 0.3, 0.8,
            is_sleeping=True, is_dreaming=False, is_thinking=True,
        )
        assert result['evolution_speed'] == pytest.approx(math.pi / 120)

    def test_bg_darkness_range(self):
        low_valence = compute_organism_params(
            self._default_drives(), 0.0, 0.3, 0.8, False, False, False,
        )
        high_valence = compute_organism_params(
            self._default_drives(), 1.0, 0.3, 0.8, False, False, False,
        )
        assert low_valence['bg_darkness'] == pytest.approx(0.92)
        assert high_valence['bg_darkness'] == pytest.approx(0.87)


# ── Window state lounge field tests ──

# Mock db and pipeline.scene before importing window_state
_mock_db = MagicMock()
_original_db = sys.modules.get("db")
sys.modules["db"] = _mock_db

_mock_scene = MagicMock()
sys.modules.setdefault("pipeline", MagicMock())
sys.modules["pipeline.scene"] = _mock_scene


@dataclass
class _FakeLayers:
    def to_dict(self):
        return {'background': 'bg', 'shop': 'shop', 'items': [],
                'character': 'char',
                'character_position': {'x': 0, 'y': 0, 'width': 64, 'height': 128},
                'foreground': [], 'weather': 'clear', 'scene_id': 'test'}


_mock_scene.build_scene_layers = AsyncMock(return_value=_FakeLayers())
_mock_scene.get_time_of_day = MagicMock(return_value='morning')
_mock_scene.resolve_sprite_state = MagicMock(return_value='thinking')
_mock_scene.resolve_time_of_day = MagicMock(return_value='afternoon')

from models.state import DrivesState, RoomState, EngagementState

# Re-import window_state fresh with our mocks
if 'window_state' in sys.modules:
    del sys.modules['window_state']
import window_state


def _make_drives():
    return DrivesState(
        social_hunger=0.4, curiosity=0.6, expression_need=0.7,
        rest_need=0.2, energy=0.8, mood_valence=0.5, mood_arousal=0.3,
    )


def _setup_db_mocks():
    _mock_db.get_drives_state = AsyncMock(return_value=_make_drives())
    _mock_db.get_room_state = AsyncMock(return_value=RoomState(weather='clear', shop_status='open'))
    _mock_db.get_engagement_state = AsyncMock(return_value=EngagementState(status='none'))
    _mock_db.get_recent_text_fragments = AsyncMock(return_value=[])
    _mock_db.get_shelf_assignments = AsyncMock(return_value=[])
    _mock_db.get_active_threads = AsyncMock(return_value=[])
    _mock_db.get_recent_events = AsyncMock(return_value=[])
    _mock_db.get_budget_remaining = AsyncMock(return_value={'budget': 5.0, 'spent': 0, 'remaining': 5.0})
    _mock_db.get_last_cycle_log = AsyncMock(return_value={
        'body_state': 'sitting', 'gaze': 'away_thinking', 'expression': 'neutral',
        'internal_monologue': 'Thinking about the nature of silence...',
        'actions': [], 'next_cycle_hints': [], 'dialogue': None,
        'mode': 'idle', 'routing_focus': 'idle',
    })
    _mock_db.count_cycle_logs = AsyncMock(return_value=4231)


@pytest.mark.asyncio
async def test_initial_state_includes_lounge_fields():
    """build_initial_state includes drives, mood, energy, organism_params."""
    _setup_db_mocks()

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 26, 10, 0, 0, tzinfo=timezone.utc)
    )

    # Top-level lounge fields
    assert 'drives' in result
    assert result['drives']['curiosity'] == pytest.approx(0.6)
    assert result['drives']['social_hunger'] == pytest.approx(0.4)
    assert result['drives']['expression_need'] == pytest.approx(0.7)

    assert 'mood' in result
    assert result['mood']['valence'] == pytest.approx(0.5)
    assert result['mood']['arousal'] == pytest.approx(0.3)

    assert result['energy'] == pytest.approx(0.8)
    assert result['inner_voice'] == 'Thinking about the nature of silence...'
    assert result['engagement_state'] == 'none'
    assert result['current_action'] == 'idle'
    assert result['is_sleeping'] is False
    assert result['cycle_count'] == 4231


@pytest.mark.asyncio
async def test_initial_state_organism_params():
    """build_initial_state organism_params match expected values."""
    _setup_db_mocks()

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 26, 10, 0, 0, tzinfo=timezone.utc)
    )

    params = result['organism_params']
    # is_thinking=False for initial state, is_sleeping=False, arousal=0.3 < 0.6
    assert params['evolution_speed'] == pytest.approx(math.pi / 45)
    assert params['complexity'] == pytest.approx(8 - 0.6 * 4)
    assert params['stroke_alpha'] == pytest.approx(40 + 0.8 * 80)
    assert params['thinking_boost'] is False
    assert params['dream_flare'] is False


@pytest.mark.asyncio
async def test_cycle_broadcast_includes_lounge_fields():
    """build_cycle_broadcast includes drives, mood, energy, organism_params."""
    _setup_db_mocks()

    cycle_log = {
        'routing_focus': 'reading',
        'gaze': 'away_thinking',
        'internal_monologue': 'This article is fascinating...',
    }

    result = await window_state.build_cycle_broadcast(
        cycle_log=cycle_log,
        drives=_make_drives(),
        ambient={'condition': 'clear', 'diegetic': 'Clear skies.'},
        focus=None,
        engagement=EngagementState(status='none'),
        clock_now=datetime(2026, 2, 26, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert result['drives']['curiosity'] == pytest.approx(0.6)
    assert result['mood']['valence'] == pytest.approx(0.5)
    assert result['energy'] == pytest.approx(0.8)
    assert result['inner_voice'] == 'This article is fascinating...'
    assert result['current_action'] == 'reading'
    assert result['is_sleeping'] is False
    assert isinstance(result['cycle_count'], int)


@pytest.mark.asyncio
async def test_cycle_broadcast_thinking_detection():
    """is_thinking derived from gaze or non-idle routing_focus."""
    _setup_db_mocks()

    # away_thinking gaze → is_thinking=True
    cycle_log = {'routing_focus': 'reading', 'gaze': 'away_thinking'}
    result = await window_state.build_cycle_broadcast(
        cycle_log=cycle_log, drives=_make_drives(),
        ambient=None, focus=None,
        engagement=EngagementState(status='none'),
        clock_now=datetime(2026, 2, 26, 10, 0, 0, tzinfo=timezone.utc),
    )
    assert result['organism_params']['thinking_boost'] is True


@pytest.mark.asyncio
async def test_sleeping_state_in_broadcast():
    """is_sleeping=True when shop_status is closed."""
    _setup_db_mocks()

    result = await window_state.build_cycle_broadcast(
        cycle_log={'routing_focus': 'idle'},
        drives=_make_drives(),
        ambient=None, focus=None,
        engagement=EngagementState(status='none'),
        clock_now=datetime(2026, 2, 26, 3, 0, 0, tzinfo=timezone.utc),
        shop_status='closed',
    )

    assert result['is_sleeping'] is True
    assert result['organism_params']['evolution_speed'] == pytest.approx(math.pi / 120)


@pytest.mark.asyncio
async def test_initial_state_sleeping():
    """is_sleeping=True in initial state when shop is closed."""
    _setup_db_mocks()
    _mock_db.get_room_state = AsyncMock(
        return_value=RoomState(weather='clear', shop_status='closed')
    )

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 26, 3, 0, 0, tzinfo=timezone.utc)
    )

    assert result['is_sleeping'] is True
    assert result['organism_params']['evolution_speed'] == pytest.approx(math.pi / 120)


@pytest.mark.asyncio
async def test_initial_state_no_cycle_log():
    """build_initial_state handles missing cycle log gracefully."""
    _setup_db_mocks()
    _mock_db.get_last_cycle_log = AsyncMock(return_value=None)

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 26, 10, 0, 0, tzinfo=timezone.utc)
    )

    assert result['inner_voice'] is None
    assert result['current_action'] == 'idle'


@pytest.mark.asyncio
async def test_backward_compat_existing_fields():
    """Existing fields (type, layers, text, state, timestamp) still present."""
    _setup_db_mocks()

    result = await window_state.build_initial_state(
        clock_now=datetime(2026, 2, 26, 10, 0, 0, tzinfo=timezone.utc)
    )

    assert result['type'] == 'scene_update'
    assert 'layers' in result
    assert 'text' in result
    assert 'state' in result
    assert 'timestamp' in result
    # State sub-fields still present
    assert 'status' in result['state']
    assert 'visitor_present' in result['state']
    assert 'sprite_state' in result['state']
    assert 'time_of_day' in result['state']
