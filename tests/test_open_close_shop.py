"""Tests for TASK-035: Shop open/close as pipeline choice.

Covers:
- Auto-reopen removed — shop stays closed after close_shop
- open_shop action changes room_state from closed to open
- open_shop drive gate — blocked when energy < 0.3 or rest_need > 0.6
- open_shop prerequisite — blocked when shop already open
- close_shop prerequisite — blocked when shop already closed
- Habit gates for open_shop and close_shop
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models.pipeline import (
    Intention, ValidatedOutput, ActionRequest, ActionDecision, MotorPlan,
    ActionResult,
)
from models.state import DrivesState, EngagementState, RoomState
from pipeline.basal_ganglia import select_actions, check_habits, _passes_drive_gate
from pipeline.action_registry import ACTION_REGISTRY


# ── Helpers ──

def _make_drives(energy=0.5, social_hunger=0.0, expression_need=0.0,
                 rest_need=0.0, mood_valence=0.5):
    return DrivesState(energy=energy, social_hunger=social_hunger,
                       expression_need=expression_need, rest_need=rest_need,
                       mood_valence=mood_valence)


def _make_engagement(status='none', visitor_id=None):
    return EngagementState(status=status, visitor_id=visitor_id)


def _validated_with_intentions(intentions):
    v = ValidatedOutput(
        dialogue='...',
        internal_monologue='Thinking.',
        expression='neutral',
    )
    v.intentions = intentions
    v.approved_actions = []
    v.actions = []
    return v


@pytest.fixture(autouse=True)
def _reset_habit_cooldown():
    """Reset module-level cooldown state between tests."""
    import pipeline.basal_ganglia as bg
    bg._habit_fire_history.clear()
    bg._habit_cycle_counter = 0


# ── Action registry tests ──

class TestActionRegistryOpenShop:
    """open_shop is registered correctly."""

    def test_open_shop_exists_in_registry(self):
        assert 'open_shop' in ACTION_REGISTRY

    def test_open_shop_is_enabled(self):
        assert ACTION_REGISTRY['open_shop'].enabled is True

    def test_open_shop_is_reflexive(self):
        assert ACTION_REGISTRY['open_shop'].generative is False

    def test_open_shop_zero_energy_cost(self):
        assert ACTION_REGISTRY['open_shop'].energy_cost == 0.0

    def test_close_shop_is_reflexive(self):
        assert ACTION_REGISTRY['close_shop'].generative is False


# ── Auto-reopen removed ──

class TestAutoReopenRemoved:
    """Shop stays closed after close_shop — no auto-reopen on next cycle."""

    @pytest.mark.asyncio
    async def test_shop_stays_closed(self):
        """run_one_cycle should NOT auto-reopen the shop."""
        # We verify this by checking heartbeat.py no longer contains
        # the auto-reopen pattern. Since we can't easily run a full cycle
        # in a unit test, we verify the body handler is the only way
        # to change shop status.
        import inspect
        import heartbeat
        source = inspect.getsource(heartbeat.Heartbeat.run_one_cycle)
        assert 'update_room_state(shop_status=\'open\')' not in source
        assert 'update_room_state(shop_status="open")' not in source


# ── open_shop action via body.py ──

class TestOpenShopAction:
    """open_shop changes room_state from closed to open."""

    @pytest.mark.asyncio
    async def test_open_shop_updates_room_state(self):
        from pipeline.body import _execute_single_action
        from models.pipeline import ActionRequest

        with patch('pipeline.body.db') as mock_db:
            mock_db.update_room_state = AsyncMock()
            mock_db.append_event = AsyncMock()

            action = ActionRequest(type='open_shop', detail={})
            result = await _execute_single_action(action, visitor_id=None)

            mock_db.update_room_state.assert_called_once_with(shop_status='open')
            assert result.success is True
            assert 'room_state_updated' in result.side_effects

    @pytest.mark.asyncio
    async def test_open_shop_emits_event(self):
        from pipeline.body import _execute_single_action
        from models.pipeline import ActionRequest

        with patch('pipeline.body.db') as mock_db:
            mock_db.update_room_state = AsyncMock()
            mock_db.append_event = AsyncMock()

            action = ActionRequest(type='open_shop', detail={})
            await _execute_single_action(action, visitor_id=None)

            # Verify event emitted
            call_args = mock_db.append_event.call_args
            event = call_args[0][0]
            assert event.event_type == 'action_open_shop'


# ── Drive gates for open_shop (basal ganglia select_actions) ──

class TestOpenShopDriveGate:
    """open_shop is blocked when energy < 0.3 or rest_need > 0.6."""

    @pytest.mark.asyncio
    async def test_blocked_when_low_energy(self):
        drives = _make_drives(energy=0.2, rest_need=0.3)
        intentions = [Intention(action='open_shop', target=None,
                                content='open up', impulse=0.8)]
        validated = _validated_with_intentions(intentions)

        mock_room = MagicMock()
        mock_room.shop_status = 'closed'

        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)

            plan = await select_actions(validated, drives)

        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 1
        assert 'tired' in plan.suppressed[0].suppression_reason.lower()

    @pytest.mark.asyncio
    async def test_blocked_when_high_rest_need(self):
        drives = _make_drives(energy=0.8, rest_need=0.7)
        intentions = [Intention(action='open_shop', target=None,
                                content='open up', impulse=0.8)]
        validated = _validated_with_intentions(intentions)

        mock_room = MagicMock()
        mock_room.shop_status = 'closed'

        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)

            plan = await select_actions(validated, drives)

        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 1
        assert 'rest' in plan.suppressed[0].suppression_reason.lower()

    @pytest.mark.asyncio
    async def test_allowed_when_energy_and_rest_ok(self):
        drives = _make_drives(energy=0.8, rest_need=0.3)
        intentions = [Intention(action='open_shop', target=None,
                                content='open up', impulse=0.8)]
        validated = _validated_with_intentions(intentions)

        mock_room = MagicMock()
        mock_room.shop_status = 'closed'

        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)

            plan = await select_actions(validated, drives)

        assert len(plan.actions) == 1
        assert plan.actions[0].action == 'open_shop'
        assert plan.actions[0].status == 'approved'


# ── Prerequisites: shop status checks ──

class TestOpenShopPrerequisite:
    """open_shop is blocked when shop already open."""

    @pytest.mark.asyncio
    async def test_blocked_when_shop_already_open(self):
        drives = _make_drives(energy=0.8, rest_need=0.3)
        intentions = [Intention(action='open_shop', target=None,
                                content='open up', impulse=0.8)]
        validated = _validated_with_intentions(intentions)

        mock_room = MagicMock()
        mock_room.shop_status = 'open'

        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)

            plan = await select_actions(validated, drives)

        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 1
        assert 'already open' in plan.suppressed[0].suppression_reason.lower()


class TestCloseShopPrerequisite:
    """close_shop is blocked when shop already closed."""

    @pytest.mark.asyncio
    async def test_blocked_when_shop_already_closed(self):
        drives = _make_drives(energy=0.8)
        intentions = [Intention(action='close_shop', target=None,
                                content='close up', impulse=0.8)]
        validated = _validated_with_intentions(intentions)

        mock_room = MagicMock()
        mock_room.shop_status = 'closed'

        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)

            plan = await select_actions(validated, drives)

        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 1
        assert 'already closed' in plan.suppressed[0].suppression_reason.lower()

    @pytest.mark.asyncio
    async def test_allowed_when_shop_open(self):
        drives = _make_drives(energy=0.8)
        intentions = [Intention(action='close_shop', target=None,
                                content='close up', impulse=0.8)]
        validated = _validated_with_intentions(intentions)

        mock_room = MagicMock()
        mock_room.shop_status = 'open'

        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)

            plan = await select_actions(validated, drives)

        assert len(plan.actions) == 1
        assert plan.actions[0].action == 'close_shop'


# ── Habit auto-fire gates ──

class TestOpenShopHabitGates:
    """Habit-fired open_shop respects drive and shop status gates."""

    @pytest.mark.asyncio
    async def test_habit_open_shop_blocked_when_already_open(self):
        drives = _make_drives(energy=0.8, rest_need=0.2)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_open', 'action': 'open_shop',
            'trigger_context': 'energy:high|mood:positive|mode:idle|time:morning|visitor:false',
            'strength': 0.9, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        mock_room = MagicMock()
        mock_room.shop_status = 'open'

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)
            mock_clock.now.return_value = MagicMock(hour=9)

            result = await check_habits(drives, engagement)

        assert result is None

    @pytest.mark.asyncio
    async def test_habit_open_shop_allowed_when_closed(self):
        drives = _make_drives(energy=0.8, rest_need=0.2)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_open', 'action': 'open_shop',
            'trigger_context': 'energy:high|mood:positive|mode:idle|time:morning|visitor:false',
            'strength': 0.9, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        mock_room = MagicMock()
        mock_room.shop_status = 'closed'

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)
            mock_clock.now.return_value = MagicMock(hour=9)

            result = await check_habits(drives, engagement)

        assert result is not None
        assert isinstance(result, MotorPlan)
        assert result.actions[0].action == 'open_shop'

    @pytest.mark.asyncio
    async def test_habit_open_shop_blocked_low_energy(self):
        drives = _make_drives(energy=0.2, rest_need=0.2)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_open', 'action': 'open_shop',
            'trigger_context': 'energy:low|mood:positive|mode:idle|time:morning|visitor:false',
            'strength': 0.9, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        mock_room = MagicMock()
        mock_room.shop_status = 'closed'

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)
            mock_clock.now.return_value = MagicMock(hour=9)

            result = await check_habits(drives, engagement)

        assert result is None

    @pytest.mark.asyncio
    async def test_habit_open_shop_blocked_high_rest_need(self):
        drives = _make_drives(energy=0.8, rest_need=0.7)
        engagement = _make_engagement(status='none')

        habit = {
            'id': 'hab_open', 'action': 'open_shop',
            'trigger_context': 'energy:high|mood:positive|mode:idle|time:morning|visitor:false',
            'strength': 0.9, 'repetition_count': 10,
            'formed_at': '2026-01-01', 'last_triggered': '2026-02-01',
        }

        mock_room = MagicMock()
        mock_room.shop_status = 'closed'

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.context_bands.clock') as mock_clock:
            mock_db.get_all_habits = AsyncMock(return_value=[habit])
            mock_db.get_room_state = AsyncMock(return_value=mock_room)
            mock_clock.now.return_value = MagicMock(hour=9)

            result = await check_habits(drives, engagement)

        assert result is None


# ── Drive gate unit tests ──

class TestDriveGateUnit:
    """Direct tests for _passes_drive_gate."""

    def test_open_shop_passes_when_ok(self):
        drives = _make_drives(energy=0.5, rest_need=0.3)
        assert _passes_drive_gate('open_shop', drives) is True

    def test_open_shop_fails_low_energy(self):
        drives = _make_drives(energy=0.2, rest_need=0.3)
        assert _passes_drive_gate('open_shop', drives) is False

    def test_open_shop_fails_high_rest(self):
        drives = _make_drives(energy=0.5, rest_need=0.7)
        assert _passes_drive_gate('open_shop', drives) is False

    def test_open_shop_boundary_energy(self):
        """Energy exactly at 0.3 should fail (need > 0.3)."""
        drives = _make_drives(energy=0.3, rest_need=0.3)
        assert _passes_drive_gate('open_shop', drives) is False

    def test_open_shop_boundary_rest(self):
        """Rest need exactly at 0.6 should fail (need < 0.6)."""
        drives = _make_drives(energy=0.5, rest_need=0.6)
        assert _passes_drive_gate('open_shop', drives) is False
