"""Tests for TASK-044: Conversation integration with content.

Verifies mention_in_conversation action and topic-matching notifications
surfacing during engagement.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.pipeline import ActionResult, ActionRequest
from pipeline.body import _execute_single_action
from pipeline.action_registry import ACTION_REGISTRY


class TestMentionInConversation:
    """mention_in_conversation action — reference content without full read."""

    def test_action_in_registry(self):
        """mention_in_conversation is registered and enabled."""
        cap = ACTION_REGISTRY.get('mention_in_conversation')
        assert cap is not None
        assert cap.enabled is True

    @pytest.mark.asyncio
    async def test_mention_returns_metadata(self):
        """mention_in_conversation returns title/source without full content."""
        mock_db = MagicMock()
        mock_db.get_pool_item_by_id = AsyncMock(return_value={
            'id': 'c1',
            'title': 'Interesting Article',
            'source_channel': 'rss',
            'content_type': 'article',
        })
        mock_db.update_pool_item = AsyncMock()
        mock_db.append_event = AsyncMock()

        with patch('pipeline.body.db', mock_db):
            action = ActionRequest(
                type='mention_in_conversation',
                detail={'content_id': 'c1'},
            )
            result = await _execute_single_action(action, visitor_id='v1')

        assert result.success is True
        assert result.payload['title'] == 'Interesting Article'
        assert result.payload['source'] == 'rss'
        assert 'content_mentioned' in result.side_effects
        # Should NOT have full content in payload
        assert 'full_content' not in result.payload

    @pytest.mark.asyncio
    async def test_mention_marks_seen(self):
        """mention_in_conversation marks content as 'seen'."""
        mock_db = MagicMock()
        mock_db.get_pool_item_by_id = AsyncMock(return_value={
            'id': 'c1',
            'title': 'Test',
            'source_channel': 'rss',
            'content_type': 'article',
        })
        mock_db.update_pool_item = AsyncMock()
        mock_db.append_event = AsyncMock()

        with patch('pipeline.body.db', mock_db):
            action = ActionRequest(
                type='mention_in_conversation',
                detail={'content_id': 'c1'},
            )
            await _execute_single_action(action, visitor_id='v1')

        # Should update pool item status to 'seen'
        mock_db.update_pool_item.assert_called_once()
        call_kwargs = mock_db.update_pool_item.call_args
        assert call_kwargs[0][0] == 'c1'  # content_id
        assert call_kwargs[1]['status'] == 'seen'

    @pytest.mark.asyncio
    async def test_mention_missing_content_fails(self):
        """mention_in_conversation with unknown content_id → failure."""
        mock_db = MagicMock()
        mock_db.get_pool_item_by_id = AsyncMock(return_value=None)
        mock_db.append_event = AsyncMock()

        with patch('pipeline.body.db', mock_db):
            action = ActionRequest(
                type='mention_in_conversation',
                detail={'content_id': 'nonexistent'},
            )
            result = await _execute_single_action(action, visitor_id='v1')

        assert result.success is False
        assert 'not found' in result.error

    @pytest.mark.asyncio
    async def test_mention_no_content_id_fails(self):
        """mention_in_conversation without content_id → failure."""
        mock_db = MagicMock()
        mock_db.append_event = AsyncMock()

        with patch('pipeline.body.db', mock_db):
            action = ActionRequest(
                type='mention_in_conversation',
                detail={},
            )
            result = await _execute_single_action(action, visitor_id='v1')

        assert result.success is False
        assert 'no content_id' in result.error
