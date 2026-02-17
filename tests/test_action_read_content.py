"""Tests for read_content and save_for_later body actions.

TASK-041: Verifies that read_content fetches full text, truncates long content,
respects cooldown, and that save_for_later flags items in the content pool.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.pipeline import ActionRequest, ActionResult
from pipeline.action_registry import ACTION_REGISTRY
from pipeline.body import _execute_single_action


@pytest.fixture(autouse=True)
def _patch_body_deps():
    """Patch db, clock, and hypothalamus at the pipeline.body module level."""
    mock_db = MagicMock()
    mock_db.append_event = AsyncMock(return_value=None)
    mock_db.append_conversation = AsyncMock(return_value=None)
    mock_db.insert_text_fragment = AsyncMock(return_value=None)
    mock_db.insert_collection_item = AsyncMock(return_value=None)
    mock_db.insert_journal = AsyncMock(return_value=None)
    mock_db.update_room_state = AsyncMock(return_value=None)
    mock_db.update_engagement_state = AsyncMock(return_value=None)
    mock_db.update_visitor = AsyncMock(return_value=None)
    mock_db.get_pool_item_by_id = AsyncMock(return_value=None)
    mock_db.update_pool_item = AsyncMock(return_value=None)
    mock_db.save_content_for_later = AsyncMock(return_value=None)

    mock_clock = MagicMock()
    mock_clock.now_utc = MagicMock(
        return_value=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    )

    mock_relief = AsyncMock(return_value=None)

    with patch('pipeline.body.db', mock_db), \
         patch('pipeline.body.clock', mock_clock), \
         patch('pipeline.body.apply_expression_relief', mock_relief):
        yield mock_db, mock_clock, mock_relief


@pytest.fixture
def mock_db(_patch_body_deps):
    return _patch_body_deps[0]


def _make_pool_item(enriched_text=None, content='https://example.com/article',
                    title='Test Article', content_type='article',
                    source_channel='rss_feed'):
    """Create a mock content pool item dict."""
    return {
        'id': 'content-123',
        'title': title,
        'content': content,
        'enriched_text': enriched_text,
        'content_type': content_type,
        'source_channel': source_channel,
        'source_type': 'rss_headline',
        'status': 'unseen',
    }


class TestReadContent:
    """read_content action fetches full text from content pool."""

    @pytest.mark.asyncio
    async def test_read_content_fetches_full_text(self, mock_db):
        """Action returns full content in payload."""
        pool_item = _make_pool_item(
            enriched_text='This is the full article text about interesting things.'
        )
        mock_db.get_pool_item_by_id = AsyncMock(return_value=pool_item)

        action = ActionRequest(type='read_content', detail={'content_id': 'content-123'})
        result = await _execute_single_action(action, visitor_id=None)

        assert result.success is True
        assert result.content == 'This is the full article text about interesting things.'
        assert result.payload['full_content'] == result.content
        assert result.payload['title'] == 'Test Article'
        assert 'content_read' in result.side_effects

    @pytest.mark.asyncio
    async def test_read_content_truncates(self, mock_db):
        """Content over ~1500 tokens (6000 chars) is truncated."""
        long_text = 'x' * 7000
        pool_item = _make_pool_item(enriched_text=long_text)
        mock_db.get_pool_item_by_id = AsyncMock(return_value=pool_item)

        action = ActionRequest(type='read_content', detail={'content_id': 'content-123'})
        result = await _execute_single_action(action, visitor_id=None)

        assert result.success is True
        assert len(result.content) < 7000
        assert result.content.endswith('[...truncated]')

    @pytest.mark.asyncio
    async def test_read_content_uses_raw_content_without_enriched(self, mock_db):
        """Falls back to raw content when enriched_text is not available."""
        pool_item = _make_pool_item(enriched_text=None, content='Raw content here')
        mock_db.get_pool_item_by_id = AsyncMock(return_value=pool_item)

        action = ActionRequest(type='read_content', detail={'content_id': 'content-123'})
        result = await _execute_single_action(action, visitor_id=None)

        assert result.success is True
        assert result.content == 'Raw content here'

    @pytest.mark.asyncio
    async def test_read_content_marks_engaged(self, mock_db):
        """Content pool item is marked as engaged after reading."""
        pool_item = _make_pool_item(enriched_text='Article text.')
        mock_db.get_pool_item_by_id = AsyncMock(return_value=pool_item)

        action = ActionRequest(type='read_content', detail={'content_id': 'content-123'})
        await _execute_single_action(action, visitor_id=None)

        mock_db.update_pool_item.assert_called_once()
        call_kwargs = mock_db.update_pool_item.call_args
        assert call_kwargs.args[0] == 'content-123'
        assert call_kwargs.kwargs['status'] == 'engaged'

    @pytest.mark.asyncio
    async def test_read_content_emits_consumed_event(self, mock_db):
        """A content_consumed event is emitted for drive updates."""
        pool_item = _make_pool_item(enriched_text='Article text.')
        mock_db.get_pool_item_by_id = AsyncMock(return_value=pool_item)

        action = ActionRequest(type='read_content', detail={'content_id': 'content-123'})
        await _execute_single_action(action, visitor_id=None)

        # Check that append_event was called with content_consumed
        calls = mock_db.append_event.call_args_list
        consumed = [c for c in calls if c.args[0].event_type == 'content_consumed']
        assert len(consumed) == 1
        assert consumed[0].args[0].payload['content_id'] == 'content-123'

    @pytest.mark.asyncio
    async def test_read_content_invalid_id(self, mock_db):
        """Fails gracefully when content_id doesn't exist."""
        mock_db.get_pool_item_by_id = AsyncMock(return_value=None)

        action = ActionRequest(type='read_content', detail={'content_id': 'nonexistent'})
        result = await _execute_single_action(action, visitor_id=None)

        assert result.success is False
        assert 'not found' in result.error

    @pytest.mark.asyncio
    async def test_read_content_no_content_id(self, mock_db):
        """Fails gracefully when no content_id provided."""
        action = ActionRequest(type='read_content', detail={})
        result = await _execute_single_action(action, visitor_id=None)

        assert result.success is False
        assert 'no content_id' in result.error


    @pytest.mark.asyncio
    async def test_read_content_cooldown(self):
        """read_content has a non-zero cooldown_seconds to enforce min_cycles_between_reads.

        The basal ganglia enforces cooldown_seconds from the action registry.
        With ~3 min/cycle, 360s = ~2 cycles between reads.
        """
        cap = ACTION_REGISTRY['read_content']
        assert cap.cooldown_seconds > 0, "read_content must have a cooldown"
        # At ~3 min/cycle, cooldown should be ~2 cycles = ~360 seconds
        assert cap.cooldown_seconds >= 300, "cooldown should be at least ~2 cycles"


class TestSaveForLater:
    """save_for_later action flags content pool items."""

    @pytest.mark.asyncio
    async def test_save_for_later_flags_item(self, mock_db):
        """Content pool item gets saved_by_cortex=True."""
        action = ActionRequest(
            type='save_for_later',
            detail={'content_id': 'content-456'},
        )
        result = await _execute_single_action(action, visitor_id=None)

        assert result.success is True
        assert 'content_saved' in result.side_effects
        mock_db.save_content_for_later.assert_called_once_with('content-456')

    @pytest.mark.asyncio
    async def test_save_for_later_no_content_id(self, mock_db):
        """Fails gracefully when no content_id provided."""
        action = ActionRequest(type='save_for_later', detail={})
        result = await _execute_single_action(action, visitor_id=None)

        assert result.success is False
        assert 'no content_id' in result.error
