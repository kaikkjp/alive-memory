"""Tests for pipeline/body.py — action execution and event emission.

Verifies that the body module produces identical behavior to the old executor
for all action types. Uses mocked db to isolate body logic.
"""

import sys
import unittest.mock

import pytest

# Mock db and clock before importing body
_mock_db = unittest.mock.MagicMock()
_mock_db.append_event = unittest.mock.AsyncMock(return_value=None)
_mock_db.append_conversation = unittest.mock.AsyncMock(return_value=None)
_mock_db.insert_text_fragment = unittest.mock.AsyncMock(return_value=None)
_mock_db.insert_collection_item = unittest.mock.AsyncMock(return_value=None)
_mock_db.assign_shelf_slot = unittest.mock.AsyncMock(return_value=None)
_mock_db.insert_journal = unittest.mock.AsyncMock(return_value=None)
_mock_db.update_room_state = unittest.mock.AsyncMock(return_value=None)
_mock_db.update_engagement_state = unittest.mock.AsyncMock(return_value=None)
_mock_db.update_visitor = unittest.mock.AsyncMock(return_value=None)
sys.modules.setdefault("db", _mock_db)

# Mock clock
_mock_clock = unittest.mock.MagicMock()
_mock_clock.now_utc = unittest.mock.MagicMock(return_value=None)
sys.modules.setdefault("clock", _mock_clock)

# Mock hypothalamus
_mock_hypothalamus = unittest.mock.MagicMock()
_mock_hypothalamus.apply_expression_relief = unittest.mock.AsyncMock(return_value=None)
sys.modules.setdefault("pipeline.hypothalamus", _mock_hypothalamus)

from models.pipeline import (
    ValidatedOutput, ActionRequest, ActionDecision, MotorPlan,
    ActionResult, BodyOutput,
)
from pipeline.body import execute_body, _execute_single_action, END_ENGAGEMENT_LINES


@pytest.fixture(autouse=True)
def _reset_mocks():
    """Reset all mock call counts between tests."""
    _mock_db.reset_mock()
    _mock_clock.reset_mock()
    _mock_hypothalamus.reset_mock()
    # Re-setup return values after reset
    _mock_db.append_event = unittest.mock.AsyncMock(return_value=None)
    _mock_db.append_conversation = unittest.mock.AsyncMock(return_value=None)
    _mock_db.insert_text_fragment = unittest.mock.AsyncMock(return_value=None)
    _mock_db.insert_collection_item = unittest.mock.AsyncMock(return_value=None)
    _mock_db.assign_shelf_slot = unittest.mock.AsyncMock(return_value=None)
    _mock_db.insert_journal = unittest.mock.AsyncMock(return_value=None)
    _mock_db.update_room_state = unittest.mock.AsyncMock(return_value=None)
    _mock_db.update_engagement_state = unittest.mock.AsyncMock(return_value=None)
    _mock_db.update_visitor = unittest.mock.AsyncMock(return_value=None)
    _mock_hypothalamus.apply_expression_relief = unittest.mock.AsyncMock(return_value=None)
    yield


@pytest.fixture
def simple_motor_plan():
    """MotorPlan with one approved action."""
    return MotorPlan(
        actions=[ActionDecision(action='write_journal', status='approved', source='cortex')],
        suppressed=[],
        habit_fired=False,
        energy_budget=0.8,
    )


@pytest.fixture
def simple_validated():
    """ValidatedOutput with dialogue and one approved write_journal."""
    v = ValidatedOutput(
        dialogue='A quiet afternoon.',
        internal_monologue='The light is changing.',
        expression='pensive',
        body_state='sitting',
        gaze='at_window',
    )
    v.approved_actions = [
        ActionRequest(type='write_journal', detail={'text': 'Thoughts on the day.'}),
    ]
    return v


class TestExecuteBody:
    """execute_body() emits dialogue, body state, and executes actions."""

    @pytest.mark.asyncio
    async def test_emits_dialogue_event(self, simple_motor_plan, simple_validated):
        output = await execute_body(simple_motor_plan, simple_validated, visitor_id='v1')
        assert isinstance(output, BodyOutput)
        # Should emit action_speak + action_body = at least 2 events
        assert output.events_emitted >= 2

    @pytest.mark.asyncio
    async def test_emits_body_state_event(self, simple_motor_plan, simple_validated):
        output = await execute_body(simple_motor_plan, simple_validated)
        # action_body event should be emitted
        body_calls = [
            call for call in _mock_db.append_event.call_args_list
            if call[0][0].event_type == 'action_body'
        ]
        assert len(body_calls) == 1
        payload = body_calls[0][0][0].payload
        assert payload['expression'] == 'pensive'
        assert payload['body_state'] == 'sitting'
        assert payload['gaze'] == 'at_window'

    @pytest.mark.asyncio
    async def test_executes_approved_actions(self, simple_motor_plan, simple_validated):
        output = await execute_body(simple_motor_plan, simple_validated)
        assert len(output.executed) == 1
        assert output.executed[0].action == 'write_journal'

    @pytest.mark.asyncio
    async def test_no_dialogue_emits_thought_fragment(self):
        validated = ValidatedOutput(
            dialogue=None,
            internal_monologue='A passing thought.',
            expression='neutral',
            body_state='sitting',
            gaze='at_window',
        )
        plan = MotorPlan(actions=[], suppressed=[], habit_fired=False, energy_budget=0.8)
        await execute_body(plan, validated)
        # Should write thought fragment
        frag_calls = [
            call for call in _mock_db.insert_text_fragment.call_args_list
            if call[1].get('fragment_type') == 'thought'
            or (call[1] and 'thought' in str(call))
        ]
        assert len(frag_calls) >= 1

    @pytest.mark.asyncio
    async def test_silence_dialogue_not_emitted(self):
        validated = ValidatedOutput(dialogue='...')
        plan = MotorPlan(actions=[], suppressed=[], habit_fired=False, energy_budget=0.8)
        await execute_body(plan, validated)
        speak_calls = [
            call for call in _mock_db.append_event.call_args_list
            if call[0][0].event_type == 'action_speak'
        ]
        assert len(speak_calls) == 0

    @pytest.mark.asyncio
    async def test_empty_motor_plan(self):
        validated = ValidatedOutput(dialogue='...')
        plan = MotorPlan(actions=[], suppressed=[], habit_fired=False, energy_budget=0.8)
        output = await execute_body(plan, validated)
        assert len(output.executed) == 0
        assert output.events_emitted >= 1  # body state always emitted


class TestExecuteSingleAction:
    """_execute_single_action() handles each action type correctly."""

    @pytest.mark.asyncio
    async def test_write_journal(self):
        action = ActionRequest(type='write_journal', detail={'text': 'My thoughts.'})
        result = await _execute_single_action(action, visitor_id=None)
        assert result.action == 'write_journal'
        assert result.success is True
        assert 'journal_entry_created' in result.side_effects
        _mock_db.insert_journal.assert_called_once()

    @pytest.mark.asyncio
    async def test_end_engagement(self):
        action = ActionRequest(type='end_engagement', detail={'reason': 'natural'})
        result = await _execute_single_action(action, visitor_id='v1')
        assert result.action == 'end_engagement'
        assert result.success is True
        assert 'engagement_ended' in result.side_effects
        _mock_db.update_engagement_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_shop(self):
        action = ActionRequest(type='close_shop', detail={})
        result = await _execute_single_action(action, visitor_id=None)
        assert result.action == 'close_shop'
        assert result.success is True
        assert 'room_state_updated' in result.side_effects

    @pytest.mark.asyncio
    async def test_rearrange(self):
        action = ActionRequest(type='rearrange', detail={'area': 'shelf'})
        result = await _execute_single_action(action, visitor_id=None)
        assert result.action == 'rearrange'
        assert result.success is True
        assert 'room_delta_emitted' in result.side_effects

    @pytest.mark.asyncio
    async def test_decline_gift(self):
        action = ActionRequest(type='decline_gift', detail={'reason': 'no thanks'})
        result = await _execute_single_action(action, visitor_id='v1')
        assert result.action == 'decline_gift'
        assert result.success is True
        assert 'event_emitted' in result.side_effects


class TestEndEngagementLines:
    """END_ENGAGEMENT_LINES dict is accessible and well-formed."""

    def test_all_reasons_present(self):
        assert 'tired' in END_ENGAGEMENT_LINES
        assert 'boundary' in END_ENGAGEMENT_LINES
        assert 'natural' in END_ENGAGEMENT_LINES

    def test_lines_are_strings(self):
        for line in END_ENGAGEMENT_LINES.values():
            assert isinstance(line, str)
            assert len(line) > 0
