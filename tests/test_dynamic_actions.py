"""Tests for TASK-056 Phase 2 — dynamic action resolution in basal_ganglia.py.

Tests the 4-tier Gate 1 resolution chain:
  static registry → dynamic alias → body_state → pending
"""

import pytest
from unittest.mock import AsyncMock, patch
from models.pipeline import (
    Intention, ValidatedOutput, ActionRequest, DroppedAction,
    ActionDecision, MotorPlan,
)
from models.state import DrivesState
from pipeline.basal_ganglia import select_actions


# ── Helpers ──

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


@pytest.fixture(autouse=True)
def mock_db_base():
    """Mock pipeline.basal_ganglia.db so Gate 6 (inhibition) and dynamic resolution
    don't hit a real database.
    """
    with patch('pipeline.basal_ganglia.db') as bg_db_mock:
        # Gate 6 inhibition check needs this
        bg_db_mock.get_inhibitions_for_action = AsyncMock(return_value=[])
        # Gate 5 shop check needs this
        bg_db_mock.get_room_state = AsyncMock(return_value={'shop_status': 'open'})
        # Dynamic action resolution needs these — set as defaults (override per test)
        bg_db_mock.get_dynamic_action = AsyncMock(return_value=None)
        bg_db_mock.record_unknown_action = AsyncMock(return_value=None)
        yield bg_db_mock


@pytest.fixture
def drives():
    return DrivesState(energy=0.8, social_hunger=0.5)


# ── Tests ──

class TestDynamicActionResolution:
    """Gate 1 resolution: unknown actions route through the dynamic table."""

    @pytest.mark.asyncio
    async def test_browse_web_resolves_to_read_content(self, drives, mock_db_base):
        """An alias-status action redirects to its target and gets approved."""
        # 'look_up_info' is not in ACTION_REGISTRY — it's a user-coined action
        # that has been resolved as an alias for 'read_content'
        alias_row = {
            'action_name': 'look_up_info',
            'status': 'alias',
            'alias_for': 'read_content',
            'body_state': None,
            'attempt_count': 3,
        }
        mock_db_base.get_dynamic_action = AsyncMock(return_value=alias_row)

        intentions = [
            Intention(action='look_up_info', content='search', impulse=0.7),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context={})

        # Should resolve alias → read_content and pass remaining gates
        assert len(plan.actions) == 1
        assert plan.actions[0].action == 'read_content'
        assert plan.actions[0].status == 'approved'

    @pytest.mark.asyncio
    async def test_stand_creates_body_state_update(self, drives, mock_db_base):
        """A body_state-status action gets auto-approved with _body_state_update detail."""
        body_state_row = {
            'action_name': 'stand',
            'status': 'body_state',
            'alias_for': None,
            'body_state': '{"body_state": "standing"}',
            'attempt_count': 2,
        }
        mock_db_base.get_dynamic_action = AsyncMock(return_value=body_state_row)

        intentions = [
            Intention(action='stand', content='', impulse=0.5),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context={})

        # Body state actions are auto-approved and skip remaining gates
        assert len(plan.actions) == 1
        action = plan.actions[0]
        assert action.status == 'approved'
        assert '_body_state_update' in action.detail
        assert action.detail['_body_state_update'] == '{"body_state": "standing"}'
        assert action.detail['_original_action'] == 'stand'

    @pytest.mark.asyncio
    async def test_fly_to_moon_creates_pending_entry(self, drives, mock_db_base):
        """A truly unknown action gets recorded as pending and marked incapable."""
        mock_db_base.get_dynamic_action = AsyncMock(return_value=None)
        mock_record = AsyncMock(return_value=None)
        mock_db_base.record_unknown_action = mock_record

        intentions = [
            Intention(action='fly_to_moon', content='wheee', impulse=0.9),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context={})

        # Must be suppressed as incapable
        assert len(plan.actions) == 0
        assert len(plan.suppressed) == 1
        suppressed = plan.suppressed[0]
        assert suppressed.status == 'incapable'
        assert 'Unknown action' in suppressed.suppression_reason
        assert 'fly_to_moon' in suppressed.suppression_reason

        # Must have called record_unknown_action
        mock_record.assert_awaited_once_with('fly_to_moon')

    @pytest.mark.asyncio
    async def test_unknown_action_increments_on_repeat(self, drives, mock_db_base):
        """When get_dynamic_action returns a pending row, record_unknown_action is called again."""
        pending_row = {
            'action_name': 'teleport',
            'status': 'pending',
            'alias_for': None,
            'body_state': None,
            'attempt_count': 4,
        }
        mock_db_base.get_dynamic_action = AsyncMock(return_value=pending_row)
        mock_record = AsyncMock(return_value=None)
        mock_db_base.record_unknown_action = mock_record

        intentions = [
            Intention(action='teleport', content='anywhere', impulse=0.6),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context={})

        # Still incapable
        assert len(plan.actions) == 0
        suppressed = plan.suppressed[0]
        assert suppressed.status == 'incapable'
        # suppression reason should mention seen count (attempt_count + 1 = 5)
        assert 'teleport' in suppressed.suppression_reason

        # record_unknown_action must be called to bump the count
        mock_record.assert_awaited_once_with('teleport')

    @pytest.mark.asyncio
    async def test_alias_preserves_original_request_detail(self, drives, mock_db_base):
        """Alias resolution keeps the original ActionRequest detail payload (P1 regression)."""
        alias_row = {
            'action_name': 'look_up_info',
            'status': 'alias',
            'alias_for': 'read_content',
            'body_state': None,
            'attempt_count': 1,
        }
        mock_db_base.get_dynamic_action = AsyncMock(return_value=alias_row)

        # The cortex sends the original action name with a detail payload
        original_request = ActionRequest(
            type='look_up_info',
            detail={'content_id': 'item-42', 'source': 'collection'},
        )
        intentions = [
            Intention(action='look_up_info', content='search', impulse=0.7),
        ]
        validated = _validated_with_intentions(intentions, actions=[original_request])
        plan = await select_actions(validated, drives, context={})

        assert len(plan.actions) == 1
        approved = plan.actions[0]
        assert approved.action == 'read_content'
        # Original detail payload must survive the alias swap
        assert approved.detail.get('content_id') == 'item-42'
        assert approved.detail.get('source') == 'collection'
        # Resolver metadata must also be present
        assert approved.detail.get('_original_action') == 'look_up_info'

    @pytest.mark.asyncio
    async def test_alias_with_disabled_target_stays_incapable(self, drives, mock_db_base):
        """An alias that points to a disabled/absent target stays incapable."""
        # 'browse_web' is in the registry but disabled
        alias_row = {
            'action_name': 'surf_net',
            'status': 'alias',
            'alias_for': 'watch_video',  # watch_video exists but enabled=False
            'body_state': None,
            'attempt_count': 1,
        }
        mock_db_base.get_dynamic_action = AsyncMock(return_value=alias_row)

        intentions = [
            Intention(action='surf_net', content='look things up', impulse=0.7),
        ]
        validated = _validated_with_intentions(intentions)
        plan = await select_actions(validated, drives, context={})

        # Target watch_video is disabled — so stays incapable
        assert len(plan.actions) == 0
        suppressed = plan.suppressed[0]
        assert suppressed.status == 'incapable'
        assert 'surf_net' in suppressed.suppression_reason
        assert 'watch_video' in suppressed.suppression_reason

    @pytest.mark.asyncio
    async def test_post_x_backfills_text_from_intention_content(self, drives):
        """post_x should bridge intention.content into detail.text when detail is empty."""
        intentions = [
            Intention(action='post_x', content='hello from intention content', impulse=0.8),
        ]
        validated = _validated_with_intentions(intentions, actions=[])

        plan = await select_actions(validated, drives, context={})

        assert len(plan.actions) == 1
        approved = plan.actions[0]
        assert approved.action == 'post_x'
        assert approved.detail.get('text') == 'hello from intention content'

    @pytest.mark.asyncio
    async def test_tg_send_image_backfills_caption_from_intention_content(self, drives):
        """tg_send_image should bridge intention.content into detail.caption."""
        intentions = [
            Intention(action='tg_send_image', content='caption from intention', impulse=0.8),
        ]
        validated = _validated_with_intentions(intentions, actions=[])

        plan = await select_actions(validated, drives, context={})

        assert len(plan.actions) == 1
        approved = plan.actions[0]
        assert approved.action == 'tg_send_image'
        assert approved.detail.get('caption') == 'caption from intention'
        assert approved.detail.get('text') is None

    @pytest.mark.asyncio
    async def test_read_content_backfills_content_id_from_intention_content(self, drives):
        """read_content should extract content_id from intention.content when detail is empty."""
        intentions = [
            Intention(action='read_content', content='id:item-42', impulse=0.8),
        ]
        validated = _validated_with_intentions(intentions, actions=[])

        plan = await select_actions(validated, drives, context={})

        assert len(plan.actions) == 1
        approved = plan.actions[0]
        assert approved.action == 'read_content'
        assert approved.detail.get('content_id') == 'item-42'

    @pytest.mark.asyncio
    async def test_read_content_does_not_backfill_bare_token(self, drives):
        """read_content should not treat a bare token as content_id."""
        intentions = [
            Intention(action='read_content', content='bitcoin', impulse=0.8),
        ]
        validated = _validated_with_intentions(intentions, actions=[])

        plan = await select_actions(validated, drives, context={})

        assert len(plan.actions) == 1
        approved = plan.actions[0]
        assert approved.action == 'read_content'
        assert approved.detail.get('content_id') is None
