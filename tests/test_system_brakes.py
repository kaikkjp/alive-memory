"""Tests for system brakes — TASK-036.

Part A: Habit decay — unfired habits lose strength over time.
Part B: Mood bonus scaling — diminishing returns on mood bonus.
Part C: Energy budget enforcement — rest mode when budget exceeded.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

from models.pipeline import (
    ActionDecision, MotorPlan, ActionResult, BodyOutput,
    ValidatedOutput, CycleOutput,
)
from models.state import DrivesState, EngagementState
from db.parameters import p
from pipeline.output import (
    _decay_unfired_habits,
)


# ── Helpers ──

def _make_drives(energy=0.5, mood_valence=0.0, expression_need=0.0,
                 social_hunger=0.0, rest_need=0.3, curiosity=0.5,
                 mood_arousal=0.3):
    return DrivesState(
        energy=energy, mood_valence=mood_valence,
        expression_need=expression_need, social_hunger=social_hunger,
        rest_need=rest_need, curiosity=curiosity, mood_arousal=mood_arousal,
    )


def _make_habit(habit_id='hab_001', action='rearrange', strength=0.5,
                last_triggered=None, repetition_count=5):
    if last_triggered is None:
        last_triggered = datetime(2026, 2, 16, 0, 0, 0, tzinfo=timezone.utc).isoformat()
    return {
        'id': habit_id,
        'action': action,
        'trigger_context': 'energy:mid|mood:neutral|mode:idle|time:afternoon|visitor:false',
        'strength': strength,
        'repetition_count': repetition_count,
        'formed_at': '2026-01-01T00:00:00+00:00',
        'last_triggered': last_triggered,
    }


# ════════════════════════════════════════════════════════════════════
# Part A — Habit Decay
# ════════════════════════════════════════════════════════════════════

class TestHabitDecay:
    """Unfired habits lose strength proportional to elapsed time."""

    @pytest.mark.asyncio
    async def test_unfired_habit_decays(self):
        """A habit not fired this cycle loses strength based on elapsed hours."""
        # last_triggered 10 hours ago → decay = 0.01 * 10 = 0.10
        ten_hours_ago = (
            datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc)
            - timedelta(hours=10)
        ).isoformat()
        habit = _make_habit(strength=0.5, last_triggered=ten_hours_ago)

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.update_habit = AsyncMock()
            mock_db.delete_habit = AsyncMock()
            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)

            await _decay_unfired_habits(set())  # no actions fired

            mock_db.update_habit.assert_called_once()
            call_kwargs = mock_db.update_habit.call_args
            new_strength = call_kwargs[1]['strength'] if 'strength' in call_kwargs[1] else call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None
            # 0.5 - 0.01 * 10 = 0.40
            assert abs(new_strength - 0.40) < 0.01
            mock_db.delete_habit.assert_not_called()

    @pytest.mark.asyncio
    async def test_fired_habit_no_decay(self):
        """A habit whose action was just executed does NOT decay."""
        habit = _make_habit(action='speak', strength=0.7)

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.update_habit = AsyncMock()
            mock_db.delete_habit = AsyncMock()
            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)

            await _decay_unfired_habits({'speak'})  # speak just fired

            mock_db.update_habit.assert_not_called()
            mock_db.delete_habit.assert_not_called()

    @pytest.mark.asyncio
    async def test_habit_deleted_below_threshold(self):
        """A habit that decays below 0.05 is pruned from the DB."""
        # strength=0.06, last_triggered 2 hours ago → 0.06 - 0.01*2 = 0.04 < 0.05
        two_hours_ago = (
            datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc)
            - timedelta(hours=2)
        ).isoformat()
        habit = _make_habit(strength=0.06, last_triggered=two_hours_ago)

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.update_habit = AsyncMock()
            mock_db.delete_habit = AsyncMock()
            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)

            await _decay_unfired_habits(set())

            mock_db.delete_habit.assert_called_once_with(habit['id'])
            mock_db.update_habit.assert_not_called()

    @pytest.mark.asyncio
    async def test_decay_rate_30_hours(self):
        """A habit at 0.9 drops below 0.6 within ~30 simulated hours.
        0.9 - 0.01 * 30 = 0.60 (not below). 0.9 - 0.01 * 31 = 0.59 < 0.6."""
        thirty_one_hours_ago = (
            datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc)
            - timedelta(hours=31)
        ).isoformat()
        habit = _make_habit(strength=0.9, last_triggered=thirty_one_hours_ago)

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.update_habit = AsyncMock()
            mock_db.delete_habit = AsyncMock()
            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)

            await _decay_unfired_habits(set())

            call_kwargs = mock_db.update_habit.call_args
            new_strength = call_kwargs[1]['strength']
            # 0.9 - 0.01 * 31 = 0.59
            assert new_strength < 0.6

    @pytest.mark.asyncio
    async def test_multiple_habits_selective_decay(self):
        """Only unfired habits decay; fired ones are left alone."""
        now = datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc)
        five_hours_ago = (now - timedelta(hours=5)).isoformat()

        habit_a = _make_habit(habit_id='a', action='speak', strength=0.7,
                              last_triggered=five_hours_ago)
        habit_b = _make_habit(habit_id='b', action='rearrange', strength=0.6,
                              last_triggered=five_hours_ago)

        updated_ids = []
        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit_a, habit_b])
            mock_db.update_habit = AsyncMock(
                side_effect=lambda hid, **kw: updated_ids.append(hid)
            )
            mock_db.delete_habit = AsyncMock()
            mock_clock.now_utc.return_value = now

            # speak fired, rearrange did not
            await _decay_unfired_habits({'speak'})

            assert 'a' not in updated_ids  # speak: no decay
            assert 'b' in updated_ids      # rearrange: decayed

    @pytest.mark.asyncio
    async def test_db_error_graceful(self):
        """DB errors during decay don't crash."""
        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(side_effect=Exception("DB error"))
            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)

            # Should not raise
            await _decay_unfired_habits(set())


# ════════════════════════════════════════════════════════════════════
# Part B — Mood Bonus Scaling
# ════════════════════════════════════════════════════════════════════

class TestMoodBonusScaling:
    """Mood bonus diminishes as actions_today increases."""

    def _compute_bonus(self, actions_today: int) -> float:
        """Replicate the formula from output.py."""
        return 0.02 / (1 + actions_today / 10)

    def test_mood_bonus_first_action(self):
        """With 0 actions today, bonus is near 0.02."""
        bonus = self._compute_bonus(0)
        assert abs(bonus - 0.02) < 0.001

    def test_mood_bonus_at_10_actions(self):
        """With 10 actions today, bonus is 0.01."""
        bonus = self._compute_bonus(10)
        assert abs(bonus - 0.01) < 0.001

    def test_mood_bonus_diminishes(self):
        """After 30+ actions, bonus drops significantly."""
        bonus_30 = self._compute_bonus(30)
        bonus_0 = self._compute_bonus(0)
        assert bonus_30 < bonus_0 * 0.4  # less than 40% of initial

    def test_mood_bonus_never_negative(self):
        """Formula always returns positive for any non-negative count."""
        for count in [0, 1, 10, 100, 1000, 10000]:
            bonus = self._compute_bonus(count)
            assert bonus > 0

    def test_mood_bonus_monotonically_decreasing(self):
        """Bonus decreases as actions_today increases."""
        prev = self._compute_bonus(0)
        for count in [5, 10, 20, 50, 100]:
            current = self._compute_bonus(count)
            assert current < prev
            prev = current

    @pytest.mark.asyncio
    async def test_mood_bonus_integration(self):
        """process_output applies diminishing bonus via DB count."""
        from pipeline.output import process_output

        drives = _make_drives(mood_valence=0.0)
        body_output = BodyOutput(
            executed=[ActionResult(action='speak', success=True)],
        )
        validated = ValidatedOutput(
            internal_monologue='test',
            dialogue='hello',
        )

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock:
            mock_db.get_drives_state = AsyncMock(return_value=drives)
            mock_db.save_drives_state = AsyncMock()
            mock_db.get_engagement_state = AsyncMock(
                return_value=EngagementState(status='none')
            )
            mock_db.get_executed_action_count_today = AsyncMock(return_value=30)
            mock_db.get_all_habits = AsyncMock(return_value=[])
            mock_db.append_event = AsyncMock()
            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)

            await process_output(body_output, validated)

            # Drives should have been saved with a small bonus (30 actions → ~0.005)
            assert mock_db.save_drives_state.called
            saved_drives = mock_db.save_drives_state.call_args[0][0]
            # Bonus is 0.02 / (1 + 30/10) = 0.005
            assert saved_drives.mood_valence > 0.0
            assert saved_drives.mood_valence < 0.01  # much less than flat 0.02


# ════════════════════════════════════════════════════════════════════
# Part C — Energy Budget Enforcement
# ════════════════════════════════════════════════════════════════════

class TestEnergyBudgetEnforcement:
    """TASK-050: When daily dollar budget is spent, cortex is skipped and she rests."""

    @pytest.fixture
    def mock_heartbeat(self):
        """Create a Heartbeat instance with mocked dependencies."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        hb.running = True
        hb._stage_callback = None
        hb._error_backoff = 5
        hb._last_cycle_ts = datetime(2026, 2, 16, 11, 0, 0, tzinfo=timezone.utc)
        hb._recent_fidgets = []
        hb._arbiter_state = {
            'consume_count_today': 0, 'news_engage_count_today': 0,
            'thread_focus_count_today': 0, 'express_count_today': 0,
            'last_consume_ts': None, 'last_news_engage_ts': None,
            'last_thread_focus_ts': None, 'last_express_ts': None,
            'recent_focus_keywords': [], 'current_date_jst': '',
        }
        hb._last_creative_cycle_ts = None
        return hb

    @pytest.mark.asyncio
    async def test_budget_exceeded_forces_rest(self, mock_heartbeat):
        """When budget spent (remaining <= 0), cortex is skipped, rest log returned.

        TASK-050: No naps, no partial restore. Budget is budget.
        """
        drives = _make_drives(energy=0.4, rest_need=0.5)

        with patch('heartbeat.db') as mock_db, \
             patch('heartbeat.clock') as mock_clock, \
             patch('heartbeat.build_perceptions') as mock_sensor, \
             patch('heartbeat.perception_gate', side_effect=lambda p, v: p), \
             patch('heartbeat.apply_affect_lens', side_effect=lambda p, d: p), \
             patch('heartbeat.update_drives', return_value=(drives, [])), \
             patch('heartbeat.route') as mock_route, \
             patch('heartbeat.recall', return_value=[]), \
             patch('heartbeat.check_habits', return_value=None), \
             patch('heartbeat.cortex_call') as mock_cortex, \
             patch('heartbeat.maybe_record_moment'):

            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)
            mock_clock.now.return_value = MagicMock(
                hour=12, date=MagicMock(return_value=MagicMock(isoformat=MagicMock(return_value='2026-02-16')))
            )

            mock_db.refresh_params_cache = AsyncMock()
            mock_db.inbox_get_unread = AsyncMock(return_value=[])
            mock_db.get_drives_state = AsyncMock(return_value=drives)
            mock_db.get_engagement_state = AsyncMock(
                return_value=EngagementState(status='none')
            )
            mock_db.get_visitor = AsyncMock(return_value=None)
            mock_db.save_drives_state = AsyncMock()
            mock_db.inbox_mark_read = AsyncMock()
            mock_db.log_cycle = AsyncMock()
            mock_db.append_event = AsyncMock()
            mock_db.transaction = MagicMock(return_value=MagicMock(
                __aenter__=AsyncMock(), __aexit__=AsyncMock()
            ))

            # Budget EXCEEDED — remaining <= 0
            mock_db.get_budget_remaining = AsyncMock(
                return_value={'budget': 5.0, 'spent': 5.10, 'remaining': -0.10}
            )

            mock_perception = MagicMock()
            mock_perception.salience = 0.3
            mock_perception.p_type = 'ambient'
            mock_perception.source = 'ambient'
            mock_perception.features = {}
            mock_sensor.return_value = [mock_perception]

            mock_routing = MagicMock()
            mock_routing.focus = mock_perception
            mock_routing.cycle_type = 'idle'
            mock_routing.token_budget = 3000
            mock_routing.memory_requests = []
            mock_route.return_value = mock_routing

            result = await mock_heartbeat.run_cycle('idle')

            # Cortex should NOT have been called
            mock_cortex.assert_not_called()

            # TASK-050: budget_exhausted flag, rest routing, energy set to 0
            assert result['budget_exhausted'] is True
            assert result['llm_calls_blocked'] is True
            assert result['routing_focus'] == 'rest'
            assert result['drives']['energy'] == 0.0

    @pytest.mark.asyncio
    async def test_budget_exhausted_even_with_high_salience(self, mock_heartbeat):
        """TASK-050: Budget is absolute — no high-salience override.

        Even a visitor connection cannot bypass budget exhaustion.
        """
        drives = _make_drives(energy=0.4, rest_need=0.5)

        with patch('heartbeat.db') as mock_db, \
             patch('heartbeat.clock') as mock_clock, \
             patch('heartbeat.build_perceptions') as mock_sensor, \
             patch('heartbeat.perception_gate', side_effect=lambda p, v: p), \
             patch('heartbeat.apply_affect_lens', side_effect=lambda p, d: p), \
             patch('heartbeat.update_drives', return_value=(drives, [])), \
             patch('heartbeat.route') as mock_route, \
             patch('heartbeat.recall', return_value=[]), \
             patch('heartbeat.check_habits', return_value=None), \
             patch('heartbeat.cortex_call') as mock_cortex, \
             patch('heartbeat.maybe_record_moment'):

            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)
            mock_clock.now.return_value = MagicMock(
                hour=12, date=MagicMock(return_value=MagicMock(isoformat=MagicMock(return_value='2026-02-16')))
            )

            mock_db.refresh_params_cache = AsyncMock()
            mock_db.inbox_get_unread = AsyncMock(return_value=[])
            mock_db.get_drives_state = AsyncMock(return_value=drives)
            mock_db.get_engagement_state = AsyncMock(
                return_value=EngagementState(status='none')
            )
            mock_db.get_visitor = AsyncMock(return_value=None)
            mock_db.save_drives_state = AsyncMock()
            mock_db.inbox_mark_read = AsyncMock()
            mock_db.log_cycle = AsyncMock()
            mock_db.append_event = AsyncMock()
            mock_db.transaction = MagicMock(return_value=MagicMock(
                __aenter__=AsyncMock(), __aexit__=AsyncMock()
            ))

            # Budget EXCEEDED
            mock_db.get_budget_remaining = AsyncMock(
                return_value={'budget': 5.0, 'spent': 5.50, 'remaining': -0.50}
            )

            # HIGH salience perception — visitor connecting
            mock_perception = MagicMock()
            mock_perception.salience = 0.9
            mock_perception.p_type = 'visitor_connect'
            mock_perception.source = 'visitor:v1'
            mock_perception.features = {}
            mock_sensor.return_value = [mock_perception]

            mock_routing = MagicMock()
            mock_routing.focus = mock_perception
            mock_routing.cycle_type = 'engage'
            mock_routing.token_budget = 5000
            mock_routing.memory_requests = []
            mock_route.return_value = mock_routing

            result = await mock_heartbeat.run_cycle('idle')

            # Budget is absolute — cortex still NOT called
            mock_cortex.assert_not_called()
            assert result['budget_exhausted'] is True

    @pytest.mark.asyncio
    async def test_under_budget_runs_normally(self, mock_heartbeat):
        """Normal cycle when budget is not exceeded."""
        drives = _make_drives(energy=0.7, rest_need=0.2)

        with patch('heartbeat.db') as mock_db, \
             patch('heartbeat.clock') as mock_clock, \
             patch('heartbeat.build_perceptions') as mock_sensor, \
             patch('heartbeat.perception_gate', side_effect=lambda p, v: p), \
             patch('heartbeat.apply_affect_lens', side_effect=lambda p, d: p), \
             patch('heartbeat.update_drives', return_value=(drives, [])), \
             patch('heartbeat.route') as mock_route, \
             patch('heartbeat.recall', return_value=[]), \
             patch('heartbeat.check_habits', return_value=None), \
             patch('heartbeat.cortex_call') as mock_cortex, \
             patch('heartbeat.validate') as mock_validate, \
             patch('heartbeat.select_actions') as mock_select, \
             patch('heartbeat.execute_body') as mock_body, \
             patch('heartbeat.process_output') as mock_output, \
             patch('heartbeat.build_self_state', return_value=None), \
             patch('heartbeat.fetch_url_metadata', return_value=None), \
             patch('heartbeat.maybe_record_moment'):

            mock_clock.now_utc.return_value = datetime(2026, 2, 16, 12, 0, 0,
                                                        tzinfo=timezone.utc)
            mock_clock.now.return_value = MagicMock(hour=12)

            mock_db.refresh_params_cache = AsyncMock()
            mock_db.inbox_get_unread = AsyncMock(return_value=[])
            mock_db.get_drives_state = AsyncMock(return_value=drives)
            mock_db.get_engagement_state = AsyncMock(
                return_value=EngagementState(status='none', turn_count=0)
            )
            mock_db.get_visitor = AsyncMock(return_value=None)
            mock_db.save_drives_state = AsyncMock()
            mock_db.inbox_mark_read = AsyncMock()
            mock_db.log_cycle = AsyncMock()
            mock_db.get_recent_conversation = AsyncMock(return_value=[])
            mock_db.get_room_state = AsyncMock()
            mock_db.get_shelf_assignments = AsyncMock(return_value=[])
            mock_db.transaction = MagicMock(return_value=MagicMock(
                __aenter__=AsyncMock(), __aexit__=AsyncMock()
            ))
            # Under budget
            mock_db.get_budget_remaining = AsyncMock(
                return_value={'budget': 5.0, 'spent': 0.3, 'remaining': 4.7}
            )

            mock_perception = MagicMock()
            mock_perception.salience = 0.3
            mock_perception.p_type = 'ambient'
            mock_perception.source = 'ambient'
            mock_perception.features = {}
            mock_sensor.return_value = [mock_perception]

            mock_routing = MagicMock()
            mock_routing.focus = mock_perception
            mock_routing.cycle_type = 'idle'
            mock_routing.token_budget = 3000
            mock_routing.memory_requests = []
            mock_route.return_value = mock_routing

            from models.pipeline import CortexOutput
            mock_cortex.return_value = CortexOutput(
                internal_monologue='thinking...',
            )
            mock_validated = ValidatedOutput(internal_monologue='thinking...')
            mock_validate.return_value = mock_validated

            mock_motor = MotorPlan(actions=[], suppressed=[])
            mock_select.return_value = mock_motor
            mock_body.return_value = BodyOutput(executed=[])
            mock_output.return_value = CycleOutput()

            result = await mock_heartbeat.run_cycle('idle')

            # Cortex should have been called normally
            mock_cortex.assert_called_once()
            assert result.get('budget_exhausted') is not True
            assert result.get('budget_rest') is None or result.get('budget_rest') is not True
