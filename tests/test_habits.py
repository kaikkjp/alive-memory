"""Tests for habit tracking — Phase 4 (TASK-011a + TASK-011b).

Covers: TriggerContext canonical keys, piecewise strength curve,
habit creation, strengthening, cap at 0.9, different contexts,
timestamp management, graceful error handling, and habit auto-fire
in basal ganglia (bypassing cortex).
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models.pipeline import (
    ActionDecision, MotorPlan, ActionResult, BodyOutput, TriggerContext,
)
from models.state import DrivesState, EngagementState
from db.parameters import p
from pipeline.output import (
    _track_single_action, _track_action_patterns,
    _habit_delta,
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


def _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.0,
                 social_hunger=0.0):
    return DrivesState(energy=energy, mood_valence=mood_valence,
                       expression_need=expression_need,
                       social_hunger=social_hunger)


def _make_engagement(status='none', visitor_id=None):
    return EngagementState(status=status, visitor_id=visitor_id)


@pytest.fixture(autouse=True)
def _reset_habit_cooldown():
    """Reset module-level cooldown state between tests."""
    import pipeline.basal_ganglia as bg
    bg._habit_fire_history.clear()
    bg._habit_cycle_counter = 0


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
            s = min(p('output.habit.strength_cap'), s + _habit_delta(s))
            reps += 1
        assert reps <= 3

    def test_piecewise_curve_crosses_0_6_slower(self):
        """From 0.4, should take 3-4 reps to cross 0.6."""
        s = 0.4
        reps = 0
        while s < 0.6:
            s = min(p('output.habit.strength_cap'), s + _habit_delta(s))
            reps += 1
        assert 3 <= reps <= 4

    def test_cap_at_0_9_with_50_reps(self):
        """After 50 reps, strength must not exceed 0.9."""
        s = 0.1
        for _ in range(50):
            s = min(p('output.habit.strength_cap'), s + _habit_delta(s))
        assert s <= p('output.habit.strength_cap')


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
            assert call_kwargs.kwargs['strength'] == p('output.habit.strength_cap')

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


# ── Habit Auto-Fire Tests (TASK-011b) ──

from pipeline.basal_ganglia import check_habits


class TestCheckHabits:
    """check_habits() fires strong habits, bypassing cortex."""

    @pytest.mark.asyncio
    async def test_strong_habit_matching_context_returns_motor_plan(self):
        """Reflexive habit at strength >= 0.6 with matching context returns MotorPlan."""
        drives = _make_drives(energy=0.5, mood_valence=0.0)
        engagement = _make_engagement(status='none')

        matching_habit = {
            'id': 'hab_001', 'action': 'rearrange',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.7, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[matching_habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert result is not None
            assert isinstance(result, MotorPlan)
            assert result.habit_fired is True
            assert len(result.actions) == 1
            assert result.actions[0].action == 'rearrange'
            assert result.actions[0].source == 'habit'

    @pytest.mark.asyncio
    async def test_weak_habit_returns_none(self):
        """Habit at strength 0.59 does NOT auto-fire."""
        drives = _make_drives(energy=0.5, mood_valence=0.0)
        engagement = _make_engagement(status='none')

        weak_habit = {
            'id': 'hab_002', 'action': 'speak',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.59, 'repetition_count': 5,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[weak_habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert result is None

    @pytest.mark.asyncio
    async def test_multiple_matching_habits_strongest_wins(self):
        """When multiple reflexive habits match, the strongest one fires."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.5)
        engagement = _make_engagement(status='none')

        trigger = 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false'
        habits = [
            {'id': 'hab_a', 'action': 'rearrange', 'trigger_context': trigger,
             'strength': 0.65, 'repetition_count': 8,
             'formed_at': '2026-01-01', 'last_triggered': '2026-02-01'},
            {'id': 'hab_b', 'action': 'express_thought', 'trigger_context': trigger,
             'strength': 0.8, 'repetition_count': 15,
             'formed_at': '2026-01-01', 'last_triggered': '2026-02-01'},
            {'id': 'hab_c', 'action': 'end_engagement', 'trigger_context': trigger,
             'strength': 0.7, 'repetition_count': 10,
             'formed_at': '2026-01-01', 'last_triggered': '2026-02-01'},
        ]

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=habits)
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert result is not None
            assert isinstance(result, MotorPlan)
            assert result.actions[0].action == 'express_thought'
            assert result.actions[0].impulse == 0.8

    @pytest.mark.asyncio
    async def test_no_matching_context_returns_none(self):
        """Habits exist but none match the current context → None."""
        drives = _make_drives(energy=0.2, mood_valence=-0.5)  # low energy, negative mood
        engagement = _make_engagement(status='none')

        # This habit's trigger context won't match the drives above
        mismatched_habit = {
            'id': 'hab_003', 'action': 'speak',
            'trigger_context': 'energy:high|mood:positive|mode:engaged|time:morning|visitor:true',
            'strength': 0.9, 'repetition_count': 20,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[mismatched_habit])
            mock_clock.now.return_value = MagicMock(hour=23)  # night

            result = await check_habits(drives, engagement)

            assert result is None

    @pytest.mark.asyncio
    async def test_no_habits_returns_none(self):
        """Empty habits table → None."""
        drives = _make_drives()
        engagement = _make_engagement()

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert result is None

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self):
        """DB failure during habit check → None (graceful degradation)."""
        drives = _make_drives()
        engagement = _make_engagement()

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(side_effect=Exception("DB error"))
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert result is None

    @pytest.mark.asyncio
    async def test_exact_threshold_fires(self):
        """Habit at exactly 0.6 should fire when drive gate is met."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.5)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_edge', 'action': 'express_thought',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.6, 'repetition_count': 8,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert result is not None
            assert result.actions[0].action == 'express_thought'

    @pytest.mark.asyncio
    async def test_motor_plan_structure(self):
        """Verify the returned MotorPlan has correct structure for reflexive habit."""
        drives = _make_drives(energy=0.5, mood_valence=0.0)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_struct', 'action': 'rearrange',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.75, 'repetition_count': 12,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert isinstance(result, MotorPlan)
            assert result.habit_fired is True
            assert result.suppressed == []
            action = result.actions[0]
            assert action.status == 'approved'
            assert action.source == 'habit'
            assert action.impulse == 0.75
            assert action.priority == 0.75


# ── Reflexive vs Generative Habit Tests (TASK-032) ──

from models.pipeline import HabitBoost


class TestReflexiveVsGenerativeHabits:
    """check_habits() splits on generative flag: reflexive auto-fires,
    generative returns HabitBoost instead of MotorPlan."""

    @pytest.mark.asyncio
    async def test_reflexive_habit_autofires(self):
        """Rearrange (generative=False) at strength 0.6 returns MotorPlan."""
        drives = _make_drives(energy=0.5, mood_valence=0.0)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_reflex', 'action': 'rearrange',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.6, 'repetition_count': 8,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert isinstance(result, MotorPlan)
            assert result.habit_fired is True
            assert result.actions[0].action == 'rearrange'

    @pytest.mark.asyncio
    async def test_generative_habit_boosts_impulse(self):
        """Write_journal (generative=True) at strength 0.6 returns HabitBoost,
        NOT MotorPlan — cortex must still run."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.5)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_gen', 'action': 'write_journal',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.7, 'repetition_count': 12,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert isinstance(result, HabitBoost)
            assert result.action == 'write_journal'
            assert result.strength == 0.7
            assert result.habit_id == 'hab_gen'

    @pytest.mark.asyncio
    async def test_speak_habit_returns_boost(self):
        """Speak (generative=True) at strength 0.8 returns HabitBoost."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, social_hunger=0.5)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_speak', 'action': 'speak',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.8, 'repetition_count': 15,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert isinstance(result, HabitBoost)
            assert result.action == 'speak'

    @pytest.mark.asyncio
    async def test_express_thought_reflexive_autofires(self):
        """Express_thought (generative=False) at strength 0.65 returns MotorPlan."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.5)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_expr', 'action': 'express_thought',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.65, 'repetition_count': 9,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert isinstance(result, MotorPlan)
            assert result.actions[0].action == 'express_thought'

    @pytest.mark.asyncio
    async def test_post_x_draft_returns_boost(self):
        """Post_x_draft (generative=True) at strength 0.75 returns HabitBoost."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.5)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_post', 'action': 'post_x_draft',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.75, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert isinstance(result, HabitBoost)
            assert result.action == 'post_x_draft'

    @pytest.mark.asyncio
    async def test_strongest_generative_vs_reflexive(self):
        """When strongest habit is generative, returns HabitBoost even if
        weaker reflexive habits exist."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.5)
        engagement = _make_engagement(status='none')

        trigger = 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false'
        habits = [
            {'id': 'hab_r', 'action': 'rearrange', 'trigger_context': trigger,
             'strength': 0.65, 'repetition_count': 8,
             'formed_at': '2026-01-01', 'last_triggered': '2026-02-01'},
            {'id': 'hab_g', 'action': 'write_journal', 'trigger_context': trigger,
             'strength': 0.8, 'repetition_count': 15,
             'formed_at': '2026-01-01', 'last_triggered': '2026-02-01'},
        ]

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=habits)
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            # Strongest is write_journal (0.8) which is generative → HabitBoost
            assert isinstance(result, HabitBoost)
            assert result.action == 'write_journal'

    @pytest.mark.asyncio
    async def test_unknown_action_treated_as_reflexive(self):
        """If an action isn't in ACTION_REGISTRY, treat as reflexive (auto-fire)."""
        drives = _make_drives(energy=0.5, mood_valence=0.0)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_unknown', 'action': 'unknown_action',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.7, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            # Unknown action → cap is None → not generative → MotorPlan
            assert isinstance(result, MotorPlan)


class TestHabitBoostInPrompt:
    """Verify that HabitBoost produces the right nudge text for cortex context."""

    def test_habit_boost_text_appended_to_self_state(self):
        """When habit_boost is present, self_state gets a nudge line."""
        from models.pipeline import HabitBoost

        boost = HabitBoost(action='write_journal', strength=0.7, habit_id='hab_001')
        self_state = 'RIGHT NOW:\n  You are sitting.'

        # Simulate the logic from heartbeat.py
        nudge = (f"\n  You feel drawn to {boost.action.replace('_', ' ')}"
                 f" — it's becoming a habit.")
        result = self_state + nudge

        assert 'write journal' in result
        assert "it's becoming a habit" in result

    def test_habit_boost_text_creates_self_state_if_none(self):
        """When self_state is None, habit_boost creates a minimal self_state."""
        from models.pipeline import HabitBoost

        boost = HabitBoost(action='post_x_draft', strength=0.75, habit_id='hab_002')
        self_state = None

        nudge = (f"\n  You feel drawn to {boost.action.replace('_', ' ')}"
                 f" — it's becoming a habit.")
        if self_state:
            result = self_state + nudge
        else:
            result = 'RIGHT NOW:' + nudge

        assert result.startswith('RIGHT NOW:')
        assert 'post x draft' in result
        assert "it's becoming a habit" in result

    def test_habit_boost_action_names_humanized(self):
        """Underscored action names become readable in the nudge text."""
        for action, expected in [
            ('write_journal', 'write journal'),
            ('post_x_draft', 'post x draft'),
            ('speak', 'speak'),
        ]:
            boost = HabitBoost(action=action, strength=0.6, habit_id='h')
            nudge = f"You feel drawn to {boost.action.replace('_', ' ')}"
            assert expected in nudge

    def test_habit_boost_adds_impulse_to_matching_intention(self):
        """Deterministic +0.3 impulse boost applied to matching intention."""
        from models.pipeline import Intention, ValidatedOutput

        boost = HabitBoost(action='write_journal', strength=0.7, habit_id='h')
        validated = ValidatedOutput()
        validated.intentions = [
            Intention(action='write_journal', impulse=0.5),
            Intention(action='rearrange', impulse=0.6),
        ]

        # Simulate heartbeat.py logic
        for intention in validated.intentions:
            if intention.action == boost.action:
                intention.impulse = min(1.0, intention.impulse + 0.3)
                break

        assert validated.intentions[0].impulse == pytest.approx(0.8)
        assert validated.intentions[1].impulse == pytest.approx(0.6)  # unchanged

    def test_habit_boost_impulse_capped_at_1(self):
        """Impulse boost doesn't exceed 1.0."""
        from models.pipeline import Intention, ValidatedOutput

        boost = HabitBoost(action='speak', strength=0.8, habit_id='h')
        validated = ValidatedOutput()
        validated.intentions = [Intention(action='speak', impulse=0.9)]

        for intention in validated.intentions:
            if intention.action == boost.action:
                intention.impulse = min(1.0, intention.impulse + 0.3)
                break

        assert validated.intentions[0].impulse == 1.0


# ── Drive-Gated Habit Tests ──

from pipeline.basal_ganglia import (
    _passes_drive_gate, _passes_cooldown_gate, _record_habit_fire,
    HABIT_DRIVE_GATES, HABIT_COOLDOWN_CYCLES,
)


class TestDriveGating:
    """Habits should only fire when the relevant drive supports the action."""

    def test_write_journal_blocked_low_expression(self):
        """write_journal requires expression_need > 0.2."""
        drives = _make_drives(expression_need=0.1)
        assert _passes_drive_gate('write_journal', drives) is False

    def test_write_journal_passes_high_expression(self):
        drives = _make_drives(expression_need=0.5)
        assert _passes_drive_gate('write_journal', drives) is True

    def test_write_journal_blocked_at_boundary(self):
        """Exactly 0.2 does NOT pass (> not >=)."""
        drives = _make_drives(expression_need=0.2)
        assert _passes_drive_gate('write_journal', drives) is False

    def test_express_thought_blocked_low_expression(self):
        drives = _make_drives(expression_need=0.1)
        assert _passes_drive_gate('express_thought', drives) is False

    def test_express_thought_passes_high_expression(self):
        drives = _make_drives(expression_need=0.4)
        assert _passes_drive_gate('express_thought', drives) is True

    def test_speak_blocked_low_social_hunger(self):
        drives = _make_drives(social_hunger=0.2)
        assert _passes_drive_gate('speak', drives) is False

    def test_speak_passes_high_social_hunger(self):
        drives = _make_drives(social_hunger=0.5)
        assert _passes_drive_gate('speak', drives) is True

    def test_rearrange_blocked_low_energy(self):
        drives = _make_drives(energy=0.2)
        assert _passes_drive_gate('rearrange', drives) is False

    def test_rearrange_passes_high_energy(self):
        drives = _make_drives(energy=0.5)
        assert _passes_drive_gate('rearrange', drives) is True

    def test_place_item_blocked_low_energy(self):
        drives = _make_drives(energy=0.1)
        assert _passes_drive_gate('place_item', drives) is False

    def test_ungated_action_always_passes(self):
        """Actions without a drive gate (e.g. end_engagement) always pass."""
        drives = _make_drives(energy=0.1, expression_need=0.0, social_hunger=0.0)
        assert _passes_drive_gate('end_engagement', drives) is True

    def test_post_x_draft_blocked_low_expression(self):
        drives = _make_drives(expression_need=0.1)
        assert _passes_drive_gate('post_x_draft', drives) is False

    @pytest.mark.asyncio
    async def test_habit_skipped_when_drive_below_gate(self):
        """Strong write_journal habit returns None when expression_need is low."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.1)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_gated', 'action': 'write_journal',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.9, 'repetition_count': 20,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert result is None

    @pytest.mark.asyncio
    async def test_fallback_to_weaker_habit_when_strongest_gated(self):
        """If strongest habit is drive-gated, next-strongest that passes fires."""
        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.1)
        engagement = _make_engagement(status='none')

        trigger = 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false'
        habits = [
            # Strongest but gated (expression_need too low)
            {'id': 'hab_1', 'action': 'write_journal', 'trigger_context': trigger,
             'strength': 0.9, 'repetition_count': 20,
             'formed_at': '2026-01-01', 'last_triggered': '2026-02-01'},
            # Weaker but passes gate (rearrange needs energy > 0.3, we have 0.5)
            {'id': 'hab_2', 'action': 'rearrange', 'trigger_context': trigger,
             'strength': 0.7, 'repetition_count': 10,
             'formed_at': '2026-01-01', 'last_triggered': '2026-02-01'},
        ]

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=habits)
            mock_clock.now.return_value = MagicMock(hour=14)

            result = await check_habits(drives, engagement)

            assert result is not None
            assert isinstance(result, MotorPlan)
            assert result.actions[0].action == 'rearrange'


class TestCooldownGating:
    """Same action can't habit-fire twice within HABIT_COOLDOWN_CYCLES cycles."""

    def test_first_fire_always_passes(self):
        assert _passes_cooldown_gate('write_journal') is True

    def test_immediate_refire_blocked(self):
        import pipeline.basal_ganglia as bg
        bg._habit_cycle_counter = 5
        _record_habit_fire('write_journal')
        bg._habit_cycle_counter = 6
        assert _passes_cooldown_gate('write_journal') is False

    def test_refire_after_cooldown_passes(self):
        import pipeline.basal_ganglia as bg
        bg._habit_cycle_counter = 5
        _record_habit_fire('write_journal')
        bg._habit_cycle_counter = 5 + HABIT_COOLDOWN_CYCLES
        assert _passes_cooldown_gate('write_journal') is True

    def test_different_actions_independent_cooldowns(self):
        import pipeline.basal_ganglia as bg
        bg._habit_cycle_counter = 5
        _record_habit_fire('write_journal')
        bg._habit_cycle_counter = 6
        # write_journal is on cooldown, but rearrange is not
        assert _passes_cooldown_gate('write_journal') is False
        assert _passes_cooldown_gate('rearrange') is True

    @pytest.mark.asyncio
    async def test_habit_blocked_by_cooldown_in_check_habits(self):
        """check_habits returns None when action is on cooldown."""
        import pipeline.basal_ganglia as bg

        drives = _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.5)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_cd', 'action': 'write_journal',
            'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
            'strength': 0.9, 'repetition_count': 20,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_clock.now.return_value = MagicMock(hour=14)

            # First call fires (cycle 1)
            result1 = await check_habits(drives, engagement)
            assert result1 is not None

            # Second call blocked by cooldown (cycle 2)
            result2 = await check_habits(drives, engagement)
            assert result2 is None

            # Third call also blocked (cycle 3)
            result3 = await check_habits(drives, engagement)
            assert result3 is None

            # Fourth call passes — cooldown of 3 cycles elapsed
            result4 = await check_habits(drives, engagement)
            assert result4 is not None


class TestCloseShopGating:
    """close_shop habit should only fire if shop is actually open."""

    @pytest.mark.asyncio
    async def test_close_shop_blocked_when_already_closed(self):
        drives = _make_drives(energy=0.8, mood_valence=0.5)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_close', 'action': 'close_shop',
            'trigger_context': 'energy:high|mood:positive|mode:idle|time:night|visitor:false',
            'strength': 0.9, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        mock_room = MagicMock()
        mock_room.shop_status = 'closed'

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)
            mock_clock.now.return_value = MagicMock(hour=23)

            result = await check_habits(drives, engagement)

            assert result is None

    @pytest.mark.asyncio
    async def test_close_shop_allowed_when_open(self):
        drives = _make_drives(energy=0.8, mood_valence=0.5)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_close', 'action': 'close_shop',
            'trigger_context': 'energy:high|mood:positive|mode:idle|time:night|visitor:false',
            'strength': 0.9, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        mock_room = MagicMock()
        mock_room.shop_status = 'open'

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)
            mock_clock.now.return_value = MagicMock(hour=23)

            result = await check_habits(drives, engagement)

            assert result is not None
            assert isinstance(result, MotorPlan)
            assert result.actions[0].action == 'close_shop'
