"""Tests for pipeline/basal_ganglia.py — Phase 2 multi-intention selection."""

import pytest
from unittest.mock import AsyncMock, patch
from models.pipeline import (
    Intention, ValidatedOutput, ActionRequest, DroppedAction,
    ActionDecision, MotorPlan,
)
from models.state import DrivesState
from pipeline.basal_ganglia import select_actions, _calculate_priority


# ── Fixtures ──

@pytest.fixture(autouse=True)
def mock_db():
    """Mock db module so Gate 6 (inhibition check) doesn't hit real DB."""
    with patch('pipeline.basal_ganglia.db') as m:
        m.get_inhibitions_for_action = AsyncMock(return_value=[])
        yield m

@pytest.fixture
def drives():
    return DrivesState(energy=0.8, social_hunger=0.5)


@pytest.fixture
def low_energy_drives():
    return DrivesState(energy=0.1, social_hunger=0.5)


@pytest.fixture
def context_with_visitor():
    return {'visitor_present': True, 'turn_count': 5, 'mode': 'engage'}


@pytest.fixture
def context_no_visitor():
    return {'visitor_present': False, 'turn_count': 0, 'mode': 'idle'}


def _validated_with_intentions(intentions: list[Intention],
                               actions: list[ActionRequest] = None,
                               dropped: list[DroppedAction] = None) -> ValidatedOutput:
    """Build a ValidatedOutput with intentions for testing."""
    v = ValidatedOutput(
        dialogue='...',
        internal_monologue='Thinking.',
        expression='neutral',
    )
    v.intentions = intentions
    if actions:
        v.approved_actions = list(actions)
        v.actions = list(actions)
    else:
        v.approved_actions = []
        v.actions = []
    if dropped:
        v.dropped_actions = list(dropped)
    return v


# ── Test: Multi-intention selection ──

class TestMultiIntentionSelection:
    """Multiple intentions get priority-sorted and all valid ones fire."""

    @pytest.mark.asyncio
    async def test_strongest_impulse_has_highest_priority(self, drives, context_no_visitor):
        intentions = [
            Intention(action='write_journal', content='day thoughts', impulse=0.3),
            Intention(action='rearrange', content='shelf', impulse=0.9),
            Intention(action='express_thought', content='hmm', impulse=0.5),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context=context_no_visitor)

        assert len(plan.actions) == 3
        # Sorted by priority descending
        assert plan.actions[0].action == 'rearrange'
        assert plan.actions[0].priority > plan.actions[1].priority

    @pytest.mark.asyncio
    async def test_all_valid_intentions_approved(self, drives, context_no_visitor):
        intentions = [
            Intention(action='write_journal', content='note', impulse=0.7),
            Intention(action='express_thought', content='...', impulse=0.4),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context=context_no_visitor)

        assert len(plan.actions) == 2
        for d in plan.actions:
            assert d.status == 'approved'

    @pytest.mark.asyncio
    async def test_empty_intentions_returns_empty_plan(self, drives):
        validated = _validated_with_intentions([])
        plan = await select_actions(validated, drives, context={})
        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 0


# ── Test: Gate 1 — Unknown action ──

class TestGateUnknownAction:

    @pytest.mark.asyncio
    async def test_unknown_action_incapable(self, drives):
        intentions = [
            Intention(action='fly_to_moon', content='whee', impulse=0.9),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context={})

        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 1
        assert plan.suppressed[0].status == 'incapable'
        assert 'Unknown action' in plan.suppressed[0].suppression_reason


# ── Test: Gate 2 — Disabled action ──

class TestGateDisabledAction:

    @pytest.mark.asyncio
    async def test_disabled_action_incapable(self, drives):
        intentions = [
            Intention(action='browse_web', content='search for cats', impulse=0.8),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context={})

        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 1
        assert plan.suppressed[0].status == 'incapable'
        assert 'Cannot do this yet' in plan.suppressed[0].suppression_reason


# ── Test: Gate 3 — Prerequisites ──

class TestGatePrerequisites:

    @pytest.mark.asyncio
    async def test_speak_without_visitor_suppressed(self, drives, context_no_visitor):
        intentions = [
            Intention(action='speak', target='visitor', content='hello', impulse=0.9),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context=context_no_visitor)

        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 1
        assert plan.suppressed[0].status == 'suppressed'
        assert 'no visitor present' in plan.suppressed[0].suppression_reason

    @pytest.mark.asyncio
    async def test_speak_with_visitor_approved(self, drives, context_with_visitor):
        intentions = [
            Intention(action='speak', target='visitor', content='hello', impulse=0.9),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context=context_with_visitor)

        assert len(plan.actions) == 1
        assert plan.actions[0].status == 'approved'

    @pytest.mark.asyncio
    async def test_end_engagement_low_turn_count(self, drives):
        context = {'visitor_present': True, 'turn_count': 1, 'mode': 'engage'}
        intentions = [
            Intention(action='end_engagement', content='', impulse=0.6),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context=context)

        assert len(plan.actions) == 0
        assert plan.suppressed[0].status == 'suppressed'
        assert 'turn_count < 3' in plan.suppressed[0].suppression_reason


# ── Test: Gate 4 — Cooldown ──

class TestGateCooldown:

    @pytest.mark.asyncio
    async def test_recently_used_action_deferred(self, drives):
        from pipeline.action_registry import ACTION_REGISTRY
        import clock

        cap = ACTION_REGISTRY['rearrange']
        # Simulate action used 10 seconds ago, cooldown is 300s
        original_last_used = cap.last_used
        original_cooldown = cap.cooldown_seconds
        try:
            cap.last_used = clock.now_utc()
            cap.cooldown_seconds = 300
            intentions = [
                Intention(action='rearrange', content='shelf', impulse=0.8),
            ]
            validated = _validated_with_intentions(intentions)
            plan = await select_actions(validated, drives, context={})

            assert len(plan.actions) == 0
            assert len(plan.suppressed) == 1
            assert plan.suppressed[0].status == 'deferred'
            assert 'Too soon' in plan.suppressed[0].suppression_reason
        finally:
            cap.last_used = original_last_used
            cap.cooldown_seconds = original_cooldown

    @pytest.mark.asyncio
    async def test_action_past_cooldown_approved(self, drives):
        from pipeline.action_registry import ACTION_REGISTRY
        from datetime import timedelta
        import clock

        cap = ACTION_REGISTRY['rearrange']
        original_last_used = cap.last_used
        original_cooldown = cap.cooldown_seconds
        try:
            cap.last_used = clock.now_utc() - timedelta(seconds=600)
            cap.cooldown_seconds = 300
            intentions = [
                Intention(action='rearrange', content='shelf', impulse=0.8),
            ]
            validated = _validated_with_intentions(intentions)
            plan = await select_actions(validated, drives, context={})

            assert len(plan.actions) == 1
            assert plan.actions[0].status == 'approved'
        finally:
            cap.last_used = original_last_used
            cap.cooldown_seconds = original_cooldown


# ── Test: Gate 5 — Energy gating (TASK-050: REMOVED) ──
# Energy gate removed in TASK-050. Real-dollar budget check is in heartbeat.py,
# not in basal_ganglia. Actions are gated by budget at cycle level, not per-action.


# ── Test: No energy gate in basal ganglia (TASK-050) ──

class TestNoEnergyGate:
    """TASK-050: Verify no energy cost check exists in basal ganglia."""

    @pytest.mark.asyncio
    async def test_no_energy_gate_in_selection(self):
        """Actions are approved regardless of energy level — budget is checked elsewhere."""
        low_energy_drives = DrivesState(energy=0.1, social_hunger=0.5)
        intentions = [
            Intention(action='speak', target='visitor', content='hi', impulse=0.9),
        ]
        context = {'visitor_present': True, 'turn_count': 5}
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, low_energy_drives, context=context)

        # speak is approved even with low energy — budget check is in heartbeat
        assert len(plan.actions) == 1
        assert plan.actions[0].status == 'approved'


# ── Test: Priority calculation ──

class TestPriorityCalculation:

    def test_visitor_target_gets_social_boost(self):
        intention = Intention(action='speak', target='visitor', impulse=0.5)
        drives = DrivesState(social_hunger=0.8, energy=0.8)
        priority = _calculate_priority(intention, drives)

        # base=0.5 + 0.8*0.3=0.74 (TASK-014: coefficient increased to 0.3)
        assert priority == pytest.approx(0.74, abs=0.01)

    def test_non_visitor_target_no_boost(self):
        intention = Intention(action='write_journal', target='journal', impulse=0.5)
        drives = DrivesState(social_hunger=0.8, energy=0.8)
        priority = _calculate_priority(intention, drives)

        assert priority == pytest.approx(0.5, abs=0.01)

    def test_priority_capped_at_1(self):
        intention = Intention(action='speak', target='visitor', impulse=0.95)
        drives = DrivesState(social_hunger=1.0, energy=0.8)
        priority = _calculate_priority(intention, drives)

        # base=0.95 + 1.0*0.3=1.25, capped at 1.0
        assert priority == 1.0


# ── Test: max_per_cycle enforcement ──

class TestMaxPerCycle:

    @pytest.mark.asyncio
    async def test_duplicate_action_type_only_one_fires(self, drives):
        intentions = [
            Intention(action='write_journal', content='thought 1', impulse=0.9),
            Intention(action='write_journal', content='thought 2', impulse=0.7),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context={})

        # max_per_cycle for write_journal is 1
        approved_journals = [a for a in plan.actions if a.action == 'write_journal']
        assert len(approved_journals) == 1
        # The stronger one should win (it's first after sort)
        assert approved_journals[0].impulse == 0.9


# ── Test: Backward compatibility ──

class TestBackwardCompat:

    @pytest.mark.asyncio
    async def test_no_intentions_uses_phase1_passthrough(self, drives):
        """When no intentions are present, fall back to Phase 1 behavior."""
        validated = ValidatedOutput(
            dialogue='Hello there.',
            internal_monologue='Someone arrived.',
        )
        validated.approved_actions = [
            ActionRequest(type='write_journal', detail={'text': 'A quiet day.'}),
        ]
        validated.dropped_actions = [
            DroppedAction(
                action=ActionRequest(type='end_engagement', detail={'reason': 'tired'}),
                reason='turn_count < 3',
            ),
        ]
        # Ensure no intentions
        validated.intentions = []

        plan = await select_actions(validated, drives)

        assert len(plan.actions) == 1
        assert plan.actions[0].action == 'write_journal'
        assert plan.actions[0].impulse == 1.0  # Phase 1 default
        assert plan.actions[0].priority == 1.0  # Phase 1 default
        assert len(plan.suppressed) == 1
        assert plan.suppressed[0].action == 'end_engagement'


# ── Test: Validator-dropped actions in suppressed list ──

class TestValidatorDropped:

    @pytest.mark.asyncio
    async def test_validator_dropped_appears_in_suppressed(self, drives, context_no_visitor):
        intentions = [
            Intention(action='write_journal', content='note', impulse=0.7),
        ]
        dropped = [
            DroppedAction(
                action=ActionRequest(type='end_engagement', detail={}),
                reason='turn_count < 3',
            ),
        ]
        validated = _validated_with_intentions(intentions, dropped=dropped)
        plan = await select_actions(validated, drives, context=context_no_visitor)

        # Journal approved via intention gates, end_engagement in suppressed from validator
        assert len(plan.actions) == 1
        suppressed_types = [s.action for s in plan.suppressed]
        assert 'end_engagement' in suppressed_types
        validator_suppressed = [s for s in plan.suppressed if s.action == 'end_engagement']
        assert 'Validator:' in validator_suppressed[0].suppression_reason


# ── Test: Detail dict passthrough ──

class TestDetailPassthrough:

    @pytest.mark.asyncio
    async def test_approved_action_carries_detail(self, drives, context_no_visitor):
        """Basal ganglia sets detail from matching ActionRequest."""
        intentions = [
            Intention(action='write_journal', content='note', impulse=0.7),
        ]
        actions = [
            ActionRequest(type='write_journal', detail={'text': 'My deep thoughts.'}),
        ]
        validated = _validated_with_intentions(intentions, actions=actions)
        plan = await select_actions(validated, drives, context=context_no_visitor)

        assert len(plan.actions) == 1
        assert plan.actions[0].detail == {'text': 'My deep thoughts.'}
