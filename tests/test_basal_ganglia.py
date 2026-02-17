"""Tests for pipeline/basal_ganglia.py — stub passthrough in Phase 1."""

import pytest
from models.pipeline import (
    ValidatedOutput, ActionRequest, DroppedAction,
    ActionDecision, MotorPlan,
)
from models.state import DrivesState
from pipeline.basal_ganglia import select_actions


@pytest.fixture
def drives():
    return DrivesState(energy=0.8)


@pytest.fixture
def validated_with_actions():
    """ValidatedOutput with approved and dropped actions."""
    v = ValidatedOutput(
        dialogue='Hello there.',
        internal_monologue='Someone arrived.',
        expression='neutral',
        body_state='sitting',
        gaze='at_visitor',
    )
    v.approved_actions = [
        ActionRequest(type='write_journal', detail={'text': 'A quiet day.'}),
        ActionRequest(type='rearrange', detail={'area': 'shelf'}),
    ]
    v.dropped_actions = [
        DroppedAction(
            action=ActionRequest(type='end_engagement', detail={'reason': 'tired'}),
            reason='turn_count < 3',
        ),
    ]
    return v


class TestStubPassthrough:
    """Phase 1 basal ganglia passes all approved actions through unchanged."""

    @pytest.mark.asyncio
    async def test_approved_actions_become_motor_plan_actions(self, validated_with_actions, drives):
        plan = await select_actions(validated_with_actions, drives)
        assert isinstance(plan, MotorPlan)
        assert len(plan.actions) == 2
        assert plan.actions[0].action == 'write_journal'
        assert plan.actions[1].action == 'rearrange'

    @pytest.mark.asyncio
    async def test_all_actions_approved(self, validated_with_actions, drives):
        plan = await select_actions(validated_with_actions, drives)
        for decision in plan.actions:
            assert decision.status == 'approved'
            assert decision.suppression_reason is None
            assert decision.source == 'cortex'

    @pytest.mark.asyncio
    async def test_dropped_actions_become_suppressed(self, validated_with_actions, drives):
        plan = await select_actions(validated_with_actions, drives)
        assert len(plan.suppressed) == 1
        assert plan.suppressed[0].action == 'end_engagement'
        assert plan.suppressed[0].status == 'suppressed'
        assert plan.suppressed[0].suppression_reason == 'turn_count < 3'

    @pytest.mark.asyncio
    async def test_habit_fired_always_false(self, validated_with_actions, drives):
        plan = await select_actions(validated_with_actions, drives)
        assert plan.habit_fired is False

    @pytest.mark.asyncio
    async def test_empty_actions(self, drives):
        validated = ValidatedOutput(dialogue='...')
        plan = await select_actions(validated, drives)
        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 0
        assert plan.habit_fired is False

    @pytest.mark.asyncio
    async def test_impulse_and_priority_defaults(self, validated_with_actions, drives):
        plan = await select_actions(validated_with_actions, drives)
        for decision in plan.actions:
            assert decision.impulse == 1.0
            assert decision.priority == 1.0
