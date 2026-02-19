"""Tests for pipeline/body.py — action execution and event emission.

Verifies that the body module produces identical behavior to the old executor
for all action types. Uses unittest.mock.patch to isolate body logic from
real db, clock, and hypothalamus modules.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.pipeline import (
    ValidatedOutput, ActionRequest, ActionDecision, MotorPlan,
    ActionResult, BodyOutput,
)
from pipeline.body import execute_body, _execute_single_action, END_ENGAGEMENT_LINES


@pytest.fixture(autouse=True)
def _patch_body_deps():
    """Patch db, clock, and hypothalamus at the pipeline.body module level."""
    mock_db = MagicMock()
    mock_db.append_event = AsyncMock(return_value=None)
    mock_db.append_conversation = AsyncMock(return_value=None)
    mock_db.insert_text_fragment = AsyncMock(return_value=None)
    mock_db.insert_collection_item = AsyncMock(return_value=None)
    mock_db.assign_shelf_slot = AsyncMock(return_value=None)
    mock_db.update_shelf_sprite = AsyncMock(return_value=None)
    mock_db.insert_journal = AsyncMock(return_value=None)
    mock_db.update_room_state = AsyncMock(return_value=None)
    mock_db.update_engagement_state = AsyncMock(return_value=None)
    mock_db.update_visitor = AsyncMock(return_value=None)

    mock_clock = MagicMock()
    mock_clock.now_utc = MagicMock(return_value=None)

    mock_relief = AsyncMock(return_value=None)

    with patch('pipeline.body.db', mock_db), \
         patch('pipeline.body.clock', mock_clock), \
         patch('pipeline.body.apply_expression_relief', mock_relief), \
         patch('body.internal.db', mock_db), \
         patch('body.internal.clock', mock_clock), \
         patch('body.internal.apply_expression_relief', mock_relief), \
         patch('body.executor.db', mock_db), \
         patch('body.executor.clock', mock_clock):
        yield mock_db, mock_clock, mock_relief


@pytest.fixture
def mock_db(_patch_body_deps):
    """Convenience access to the patched db mock."""
    return _patch_body_deps[0]


@pytest.fixture
def simple_motor_plan():
    """MotorPlan with one approved action."""
    return MotorPlan(
        actions=[ActionDecision(action='write_journal', status='approved', source='cortex')],
        suppressed=[],
        habit_fired=False,
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
    async def test_emits_body_state_event(self, mock_db, simple_motor_plan, simple_validated):
        output = await execute_body(simple_motor_plan, simple_validated)
        # action_body event should be emitted
        body_calls = [
            call for call in mock_db.append_event.call_args_list
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
    async def test_no_dialogue_emits_thought_fragment(self, mock_db):
        validated = ValidatedOutput(
            dialogue=None,
            internal_monologue='A passing thought.',
            expression='neutral',
            body_state='sitting',
            gaze='at_window',
        )
        plan = MotorPlan(actions=[], suppressed=[], habit_fired=False)
        await execute_body(plan, validated)
        # Should write thought fragment
        frag_calls = [
            call for call in mock_db.insert_text_fragment.call_args_list
            if call[1].get('fragment_type') == 'thought'
            or (call[1] and 'thought' in str(call))
        ]
        assert len(frag_calls) >= 1

    @pytest.mark.asyncio
    async def test_silence_dialogue_not_emitted(self, mock_db):
        validated = ValidatedOutput(dialogue='...')
        plan = MotorPlan(actions=[], suppressed=[], habit_fired=False)
        await execute_body(plan, validated)
        speak_calls = [
            call for call in mock_db.append_event.call_args_list
            if call[0][0].event_type == 'action_speak'
        ]
        assert len(speak_calls) == 0

    @pytest.mark.asyncio
    async def test_empty_motor_plan(self):
        validated = ValidatedOutput(dialogue='...')
        plan = MotorPlan(actions=[], suppressed=[], habit_fired=False)
        output = await execute_body(plan, validated)
        assert len(output.executed) == 0
        assert output.events_emitted >= 1  # body state always emitted


class TestExecuteSingleAction:
    """_execute_single_action() handles each action type correctly."""

    @pytest.mark.asyncio
    async def test_write_journal(self, mock_db):
        action = ActionRequest(type='write_journal', detail={'text': 'My thoughts.'})
        result = await _execute_single_action(action, visitor_id=None)
        assert result.action == 'write_journal'
        assert result.success is True
        assert 'journal_entry_created' in result.side_effects
        mock_db.insert_journal.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_journal_empty_text_skips(self, mock_db, _patch_body_deps):
        """write_journal with empty detail.text skips the journal write entirely."""
        _, _, mock_relief = _patch_body_deps
        action = ActionRequest(type='write_journal', detail={})
        result = await _execute_single_action(action, visitor_id=None, monologue='Some thought')
        assert result.action == 'write_journal'
        assert result.success is True
        assert 'journal_skipped_no_content' in result.side_effects
        assert 'journal_entry_created' not in result.side_effects
        mock_db.insert_journal.assert_not_called()
        # Should get half relief (write_journal_skipped), not full relief
        mock_relief.assert_called_once_with('write_journal_skipped')

    @pytest.mark.asyncio
    async def test_write_journal_whitespace_text_skips(self, mock_db, _patch_body_deps):
        """write_journal with whitespace-only detail.text skips the journal write."""
        _, _, mock_relief = _patch_body_deps
        action = ActionRequest(type='write_journal', detail={'text': '   '})
        result = await _execute_single_action(action, visitor_id=None)
        assert result.success is True
        assert 'journal_skipped_no_content' in result.side_effects
        mock_db.insert_journal.assert_not_called()
        mock_relief.assert_called_once_with('write_journal_skipped')

    @pytest.mark.asyncio
    async def test_write_journal_with_text_gets_full_relief(self, _patch_body_deps):
        """write_journal with actual text gets full relief, not skipped relief."""
        _, _, mock_relief = _patch_body_deps
        action = ActionRequest(type='write_journal', detail={'text': 'Real journal content.'})
        result = await _execute_single_action(action, visitor_id=None)
        assert 'journal_entry_created' in result.side_effects
        mock_relief.assert_called_once_with('write_journal')

    @pytest.mark.asyncio
    async def test_end_engagement(self, mock_db):
        action = ActionRequest(type='end_engagement', detail={'reason': 'natural'})
        result = await _execute_single_action(action, visitor_id='v1')
        assert result.action == 'end_engagement'
        assert result.success is True
        assert 'engagement_ended' in result.side_effects
        mock_db.update_engagement_state.assert_called_once()

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


    @pytest.mark.asyncio
    async def test_body_state_dynamic_action(self, mock_db):
        """_body_state_update detail path emits action_body event and succeeds."""
        action = ActionRequest(
            type='stand',
            detail={
                '_body_state_update': '{"body_state":"standing"}',
                '_original_action': 'stand',
            },
        )
        result = await _execute_single_action(action, visitor_id=None)
        assert result.success is True
        body_calls = [
            call for call in mock_db.append_event.call_args_list
            if call[0][0].event_type == 'action_body'
        ]
        assert len(body_calls) >= 1

    @pytest.mark.asyncio
    async def test_body_state_dynamic_action_via_motor_plan(self, mock_db):
        """execute_body() routes _body_state_update actions to the dynamic path."""
        plan = MotorPlan(
            actions=[
                ActionDecision(
                    action='stand',
                    status='approved',
                    source='cortex',
                    detail={
                        '_body_state_update': '{"body_state":"standing"}',
                        '_original_action': 'stand',
                    },
                ),
            ],
            suppressed=[],
            habit_fired=False,
        )
        validated = ValidatedOutput(
            dialogue=None,
            internal_monologue='Getting up.',
            expression='neutral',
            body_state='standing',
            gaze='forward',
        )
        output = await execute_body(plan, validated)
        assert len(output.executed) == 1
        assert output.executed[0].success is True
        body_calls = [
            call for call in mock_db.append_event.call_args_list
            if call[0][0].event_type == 'action_body'
        ]
        assert len(body_calls) >= 1


class TestModifySelf:
    """_execute_single_action() handles the modify_self action type."""

    @pytest.mark.asyncio
    async def test_modify_self_bounds_violation_fails(self, mock_db):
        """modify_self sets result.error on ValueError from set_param."""
        action = ActionRequest(
            type='modify_self',
            detail={
                'parameter': 'hypothalamus.equilibria.social_hunger',
                'value': 99.0,
                'reason': 'test bounds',
            },
        )
        mock_get_param = AsyncMock(return_value={'value': 0.5})
        mock_set_param = AsyncMock(side_effect=ValueError('above maximum'))
        with patch('db.parameters.get_param', mock_get_param), \
             patch('db.parameters.set_param', mock_set_param):
            result = await _execute_single_action(action, visitor_id=None)
        assert result.success is False
        assert 'above maximum' in result.error

    @pytest.mark.asyncio
    async def test_modify_self_success(self, mock_db):
        """modify_self succeeds, emits action_modify_self event, returns old+new values."""
        action = ActionRequest(
            type='modify_self',
            detail={
                'parameter': 'hypothalamus.equilibria.social_hunger',
                'value': 0.6,
                'reason': 'want more company',
            },
        )
        mock_get_param = AsyncMock(return_value={'value': 0.45})
        mock_set_param = AsyncMock(return_value=None)
        with patch('db.parameters.get_param', mock_get_param), \
             patch('db.parameters.set_param', mock_set_param):
            result = await _execute_single_action(action, visitor_id=None)

        assert result.success is True
        assert result.payload['parameter'] == 'hypothalamus.equilibria.social_hunger'
        assert result.payload['old_value'] == 0.45
        assert result.payload['new_value'] == 0.6
        # set_param called with correct args
        mock_set_param.assert_awaited_once_with(
            'hypothalamus.equilibria.social_hunger', 0.6,
            modified_by='self', reason='want more company',
        )
        # action_modify_self event emitted
        emitted_types = [
            call.args[0].event_type
            for call in mock_db.append_event.call_args_list
        ]
        assert 'action_modify_self' in emitted_types


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
