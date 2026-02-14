"""Tests for habit tracking — Phase 4 (TASK-011a).

Covers: TriggerContext canonical keys, piecewise strength curve,
habit creation, strengthening, cap at 0.9, different contexts,
timestamp management, and graceful error handling.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models.pipeline import (
    ActionDecision, MotorPlan, ActionResult, BodyOutput, TriggerContext,
)
from models.state import DrivesState, EngagementState
from pipeline.output import (
    _track_single_action, _track_action_patterns,
    _habit_delta, HABIT_STRENGTH_CAP,
)
from pipeline.context_bands import compute_trigger_context


# ── Helpers ──

def _make_decision(action='speak', target='visitor', impulse=0.8):
    return ActionDecision(
        action=action, content='hello', target=target,
        impulse=impulse, priority=0.8, status='approved',
        source='cortex',
    )


def _make_result(action='speak', success=True):
    return ActionResult(action=action, success=success)


def _make_motor_plan(decisions):
    return MotorPlan(actions=decisions, suppressed=[], habit_fired=False)


def _make_body_output(results):
    return BodyOutput(executed=results, energy_spent=0.1, events_emitted=0)


def _make_drives(energy=0.5, mood_valence=0.0):
    return DrivesState(energy=energy, mood_valence=mood_valence)


def _make_engagement(status='none', visitor_id=None):
    return EngagementState(status=status, visitor_id=visitor_id)


# ── TriggerContext + Canonical Key Tests ──

class TestTriggerContext:
    """TriggerContext produces deterministic canonical keys."""

    def test_to_key_format(self):
        ctx = TriggerContext(
            energy_band='mid', mood_band='neutral',
            mode='idle', time_band='afternoon',
            visitor_present=False,
        )
        assert ctx.to_key() == 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false'

    def test_to_key_deterministic(self):
        """Same inputs always produce the same key string."""
        ctx1 = TriggerContext('high', 'positive', 'engaged', 'morning', True)
        ctx2 = TriggerContext('high', 'positive', 'engaged', 'morning', True)
        assert ctx1.to_key() == ctx2.to_key()

    def test_different_contexts_different_keys(self):
        ctx1 = TriggerContext('high', 'positive', 'engaged', 'morning', True)
        ctx2 = TriggerContext('low', 'negative', 'idle', 'night', False)
        assert ctx1.to_key() != ctx2.to_key()

    def test_visitor_present_lowercase(self):
        ctx_true = TriggerContext(visitor_present=True)
        ctx_false = TriggerContext(visitor_present=False)
        assert 'visitor:true' in ctx_true.to_key()
        assert 'visitor:false' in ctx_false.to_key()


# ── compute_trigger_context Tests ──

class TestComputeTriggerContext:
    """Drives and engagement → coarse-grained bands."""

    def test_energy_bands(self):
        low = compute_trigger_context(_make_drives(energy=0.2), _make_engagement())
        mid = compute_trigger_context(_make_drives(energy=0.5), _make_engagement())
        high = compute_trigger_context(_make_drives(energy=0.8), _make_engagement())
        assert low.energy_band == 'low'
        assert mid.energy_band == 'mid'
        assert high.energy_band == 'high'

    def test_energy_boundary_low(self):
        """0.33 is mid, not low."""
        ctx = compute_trigger_context(_make_drives(energy=0.33), _make_engagement())
        assert ctx.energy_band == 'mid'

    def test_energy_boundary_high(self):
        """0.66 is mid, not high."""
        ctx = compute_trigger_context(_make_drives(energy=0.66), _make_engagement())
        assert ctx.energy_band == 'mid'

    def test_mood_bands(self):
        neg = compute_trigger_context(_make_drives(mood_valence=-0.5), _make_engagement())
        neu = compute_trigger_context(_make_drives(mood_valence=0.0), _make_engagement())
        pos = compute_trigger_context(_make_drives(mood_valence=0.5), _make_engagement())
        assert neg.mood_band == 'negative'
        assert neu.mood_band == 'neutral'
        assert pos.mood_band == 'positive'

    def test_mode_engaged(self):
        ctx = compute_trigger_context(
            _make_drives(), _make_engagement(status='engaged', visitor_id='v1'),
        )
        assert ctx.mode == 'engaged'
        assert ctx.visitor_present is True

    def test_mode_idle(self):
        ctx = compute_trigger_context(_make_drives(), _make_engagement(status='none'))
        assert ctx.mode == 'idle'
        assert ctx.visitor_present is False

    @patch('pipeline.context_bands.clock')
    def test_time_bands(self, mock_clock):
        drives = _make_drives()
        engagement = _make_engagement()

        for hour, expected in [(7, 'morning'), (14, 'afternoon'), (19, 'evening'), (23, 'night')]:
            mock_clock.now.return_value = MagicMock(hour=hour)
            ctx = compute_trigger_context(drives, engagement)
            assert ctx.time_band == expected, f"hour={hour} expected {expected}, got {ctx.time_band}"


# ── Piecewise Delta Tests ──

class TestHabitDelta:
    """Piecewise strength increments: fast/medium/slow."""

    def test_fast_below_0_4(self):
        assert _habit_delta(0.0) == 0.12
        assert _habit_delta(0.1) == 0.12
        assert _habit_delta(0.39) == 0.12

    def test_medium_0_4_to_0_6(self):
        assert _habit_delta(0.4) == 0.06
        assert _habit_delta(0.5) == 0.06
        assert _habit_delta(0.59) == 0.06

    def test_slow_above_0_6(self):
        assert _habit_delta(0.6) == 0.03
        assert _habit_delta(0.8) == 0.03
        assert _habit_delta(0.89) == 0.03

    def test_piecewise_curve_reaches_0_4_quickly(self):
        """Starting at 0.1, should cross 0.4 within 3 reps."""
        s = 0.1
        reps = 0
        while s < 0.4:
            s = min(HABIT_STRENGTH_CAP, s + _habit_delta(s))
            reps += 1
        assert reps <= 3

    def test_piecewise_curve_crosses_0_6_slower(self):
        """From 0.4, should take 3-4 reps to cross 0.6."""
        s = 0.4
        reps = 0
        while s < 0.6:
            s = min(HABIT_STRENGTH_CAP, s + _habit_delta(s))
            reps += 1
        assert 3 <= reps <= 4

    def test_cap_at_0_9_with_50_reps(self):
        """After 50 reps, strength must not exceed 0.9."""
        s = 0.1
        for _ in range(50):
            s = min(HABIT_STRENGTH_CAP, s + _habit_delta(s))
        assert s <= HABIT_STRENGTH_CAP


# ── Single Action Tracking Tests ──

class TestTrackSingleAction:
    """_track_single_action creates or strengthens habits."""

    @pytest.mark.asyncio
    async def test_new_habit_created_on_first_action(self):
        """First occurrence of an action creates a new habit at strength 0.1."""
        trigger_key = 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false'
        with patch('pipeline.output.db') as mock_db:
            mock_db.find_matching_habit = AsyncMock(return_value=None)
            mock_db.create_habit = AsyncMock(return_value='hab_001')

            await _track_single_action('speak', trigger_key)

            mock_db.create_habit.assert_called_once_with('speak', trigger_key, strength=0.1)

    @pytest.mark.asyncio
    async def test_habit_strengthens_on_repeat(self):
        """Second action in same context: 0.1 + 0.12 = 0.22."""
        existing = {
            'id': 'hab_001', 'action': 'speak',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.1, 'repetition_count': 1,
            'formed_at': '2026-01-01', 'last_triggered': '2026-01-01',
        }
        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.find_matching_habit = AsyncMock(return_value=existing)
            mock_db.update_habit = AsyncMock()
            mock_clock.now_utc.return_value = '2026-01-02T00:00:00'

            await _track_single_action('speak', existing['trigger_context'])

            mock_db.update_habit.assert_called_once()
            call_kwargs = mock_db.update_habit.call_args
            assert abs(call_kwargs.kwargs['strength'] - 0.22) < 1e-9
            assert call_kwargs.kwargs['repetition_count'] == 2
            assert call_kwargs.kwargs['last_triggered'] == '2026-01-02T00:00:00'

    @pytest.mark.asyncio
    async def test_strength_never_exceeds_0_9(self):
        """Strength is capped at 0.9 no matter how many repetitions."""
        existing = {
            'id': 'hab_001', 'action': 'speak',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.89, 'repetition_count': 50,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }
        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.find_matching_habit = AsyncMock(return_value=existing)
            mock_db.update_habit = AsyncMock()
            mock_clock.now_utc.return_value = '2026-02-02T00:00:00'

            await _track_single_action('speak', existing['trigger_context'])

            call_kwargs = mock_db.update_habit.call_args
            assert call_kwargs.kwargs['strength'] == HABIT_STRENGTH_CAP

    @pytest.mark.asyncio
    async def test_last_triggered_updated(self):
        """last_triggered is set on every strengthening."""
        existing = {
            'id': 'hab_001', 'action': 'speak',
            'trigger_context': 'k',
            'strength': 0.3, 'repetition_count': 3,
            'formed_at': '2026-01-01', 'last_triggered': '2026-01-01',
        }
        fake_now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.find_matching_habit = AsyncMock(return_value=existing)
            mock_db.update_habit = AsyncMock()
            mock_clock.now_utc.return_value = fake_now

            await _track_single_action('speak', 'k')

            call_kwargs = mock_db.update_habit.call_args
            assert call_kwargs.kwargs['last_triggered'] == fake_now


# ── Full Pipeline Integration Tests ──

class TestTrackActionPatterns:
    """_track_action_patterns processes all executed actions from motor plan."""

    @pytest.mark.asyncio
    async def test_successful_actions_tracked(self):
        """Each successful action gets tracked with proper trigger context."""
        decision = _make_decision(action='speak', target='visitor_abc')
        motor = _make_motor_plan([decision])
        body = _make_body_output([_make_result(action='speak', success=True)])

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_drives_state = AsyncMock(return_value=_make_drives())
            mock_db.get_engagement_state = AsyncMock(return_value=_make_engagement())
            mock_db.find_matching_habit = AsyncMock(return_value=None)
            mock_db.create_habit = AsyncMock(return_value='hab_001')
            mock_clock.now.return_value = MagicMock(hour=14)

            await _track_action_patterns(motor, body)

            mock_db.create_habit.assert_called_once()
            trigger_key = mock_db.create_habit.call_args[0][1]
            assert 'energy:mid' in trigger_key
            assert 'mood:neutral' in trigger_key

    @pytest.mark.asyncio
    async def test_failed_actions_not_tracked(self):
        """Failed actions should not create or strengthen habits."""
        decision = _make_decision(action='speak')
        motor = _make_motor_plan([decision])
        body = _make_body_output([_make_result(action='speak', success=False)])

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_drives_state = AsyncMock(return_value=_make_drives())
            mock_db.get_engagement_state = AsyncMock(return_value=_make_engagement())
            mock_db.find_matching_habit = AsyncMock()
            mock_db.create_habit = AsyncMock()
            mock_clock.now.return_value = MagicMock(hour=14)

            await _track_action_patterns(motor, body)

            mock_db.find_matching_habit.assert_not_called()
            mock_db.create_habit.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_drives_different_keys(self):
        """Same action with different drive states produces different habit keys."""
        decision = _make_decision(action='speak')
        motor = _make_motor_plan([decision])
        body = _make_body_output([_make_result(action='speak', success=True)])

        keys = []
        for energy in [0.2, 0.8]:
            with patch('pipeline.output.db') as mock_db, \
                 patch('pipeline.context_bands.clock') as mock_clock:
                mock_db.get_drives_state = AsyncMock(return_value=_make_drives(energy=energy))
                mock_db.get_engagement_state = AsyncMock(return_value=_make_engagement())
                mock_db.find_matching_habit = AsyncMock(return_value=None)
                mock_db.create_habit = AsyncMock(return_value='hab_x')
                mock_clock.now.return_value = MagicMock(hour=14)

                await _track_action_patterns(motor, body)
                keys.append(mock_db.create_habit.call_args[0][1])

        assert keys[0] != keys[1]
        assert 'energy:low' in keys[0]
        assert 'energy:high' in keys[1]

    @pytest.mark.asyncio
    async def test_multiple_different_actions_tracked(self):
        """Different action types each create their own habit entry."""
        d1 = _make_decision(action='speak', target='visitor_abc')
        d2 = ActionDecision(
            action='write_journal', content='reflecting', target=None,
            impulse=0.6, priority=0.6, status='approved', source='cortex',
        )
        motor = _make_motor_plan([d1, d2])
        body = _make_body_output([
            _make_result(action='speak', success=True),
            _make_result(action='write_journal', success=True),
        ])

        created = []
        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_drives_state = AsyncMock(return_value=_make_drives())
            mock_db.get_engagement_state = AsyncMock(return_value=_make_engagement())
            mock_db.find_matching_habit = AsyncMock(return_value=None)
            mock_db.create_habit = AsyncMock(
                side_effect=lambda a, c, **kw: created.append(a) or 'hab_x'
            )
            mock_clock.now.return_value = MagicMock(hour=14)

            await _track_action_patterns(motor, body)

            assert 'speak' in created
            assert 'write_journal' in created

    @pytest.mark.asyncio
    async def test_db_error_graceful_degradation(self):
        """DB errors during habit tracking don't crash the pipeline."""
        decision = _make_decision()
        motor = _make_motor_plan([decision])
        body = _make_body_output([_make_result(action='speak', success=True)])

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_drives_state = AsyncMock(side_effect=Exception("DB error"))
            mock_clock.now.return_value = MagicMock(hour=14)

            # Should not raise
            await _track_action_patterns(motor, body)
