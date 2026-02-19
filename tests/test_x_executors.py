"""Tests for body/x_social.py — X posting/replying executors (TASK-069)."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from models.pipeline import ActionRequest, ActionResult


@pytest.fixture(autouse=True)
def _patch_deps():
    """Mock all external deps for X executors."""
    with patch('body.x_social.clock') as mock_clock, \
         patch('body.x_social.check_rate_limit', new_callable=AsyncMock) as mock_rate, \
         patch('body.x_social.record_action', new_callable=AsyncMock), \
         patch('body.x_social.is_channel_enabled', new_callable=AsyncMock) as mock_chan, \
         patch('body.x_social.db') as mock_db:
        mock_clock.now_utc.return_value = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_rate.return_value = (True, '')
        mock_chan.return_value = True
        mock_db.append_event = AsyncMock()
        yield {
            'clock': mock_clock,
            'rate_limit': mock_rate,
            'channel_enabled': mock_chan,
            'db': mock_db,
        }


class TestPostX:
    """Test execute_post_x executor."""

    @pytest.mark.asyncio
    async def test_successful_post(self, _patch_deps):
        """Successful post returns x_post_id."""
        from body.x_social import execute_post_x
        action = ActionRequest(type='post_x', detail={'text': 'hello world'})

        with patch('body.x_client.post_tweet', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {'success': True, 'x_post_id': '12345'}
            result = await execute_post_x(action)

        assert result.success is True
        assert result.payload['x_post_id'] == '12345'
        assert 'x_post_live' in result.side_effects

    @pytest.mark.asyncio
    async def test_empty_text_fails(self, _patch_deps):
        """Empty text returns error."""
        from body.x_social import execute_post_x
        action = ActionRequest(type='post_x', detail={})
        result = await execute_post_x(action)
        assert result.success is False
        assert 'no post text' in result.error

    @pytest.mark.asyncio
    async def test_channel_disabled_blocks(self, _patch_deps):
        """Disabled X channel blocks posting."""
        _patch_deps['channel_enabled'].return_value = False
        from body.x_social import execute_post_x
        action = ActionRequest(type='post_x', detail={'text': 'test'})
        result = await execute_post_x(action)
        assert result.success is False
        assert 'channel disabled' in result.error

    @pytest.mark.asyncio
    async def test_rate_limit_blocks(self, _patch_deps):
        """Rate limit blocks posting."""
        _patch_deps['rate_limit'].return_value = (False, 'daily limit reached')
        from body.x_social import execute_post_x
        action = ActionRequest(type='post_x', detail={'text': 'test'})
        result = await execute_post_x(action)
        assert result.success is False
        assert 'daily limit' in result.error

    @pytest.mark.asyncio
    async def test_api_failure_returns_error(self, _patch_deps):
        """API failure propagates error."""
        from body.x_social import execute_post_x
        action = ActionRequest(type='post_x', detail={'text': 'test'})

        with patch('body.x_client.post_tweet', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {'success': False, 'error': 'rate limited'}
            result = await execute_post_x(action)

        assert result.success is False
        assert 'rate limited' in result.error


class TestReplyX:
    """Test execute_reply_x executor."""

    @pytest.mark.asyncio
    async def test_successful_reply(self, _patch_deps):
        """Successful reply returns x_post_id."""
        from body.x_social import execute_reply_x
        action = ActionRequest(type='reply_x', detail={
            'text': 'thanks!',
            'reply_to_id': '99999',
        })

        with patch('body.x_client.reply_tweet', new_callable=AsyncMock) as mock_reply:
            mock_reply.return_value = {'success': True, 'x_post_id': '12346'}
            result = await execute_reply_x(action)

        assert result.success is True
        assert result.payload['x_post_id'] == '12346'

    @pytest.mark.asyncio
    async def test_missing_reply_to_id_fails(self, _patch_deps):
        """Missing reply_to_id returns error."""
        from body.x_social import execute_reply_x
        action = ActionRequest(type='reply_x', detail={'text': 'thanks!'})
        result = await execute_reply_x(action)
        assert result.success is False
        assert 'no reply_to_id' in result.error

    @pytest.mark.asyncio
    async def test_missing_text_fails(self, _patch_deps):
        """Missing text returns error."""
        from body.x_social import execute_reply_x
        action = ActionRequest(type='reply_x', detail={'reply_to_id': '99'})
        result = await execute_reply_x(action)
        assert result.success is False
        assert 'no reply text' in result.error


class TestPostXImage:
    """Test execute_post_x_image executor."""

    @pytest.mark.asyncio
    async def test_missing_image_path_fails(self, _patch_deps):
        """Missing image_path returns error."""
        from body.x_social import execute_post_x_image
        action = ActionRequest(type='post_x_image', detail={'text': 'look'})
        result = await execute_post_x_image(action)
        assert result.success is False
        assert 'no image_path' in result.error

    @pytest.mark.asyncio
    async def test_successful_image_post(self, _patch_deps):
        """Successful image post returns x_post_id."""
        from body.x_social import execute_post_x_image
        action = ActionRequest(type='post_x_image', detail={
            'text': 'check this out',
            'image_path': '/tmp/test.png',
        })

        with patch('body.x_client.post_tweet_with_media', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {'success': True, 'x_post_id': '99999'}
            result = await execute_post_x_image(action)

        assert result.success is True
        assert result.payload['x_post_id'] == '99999'


class TestXMentionPollerCheckpoint:
    """Test that since_id always advances to the max (never backward)."""

    @pytest.mark.asyncio
    async def test_since_id_takes_max_from_batch(self, _patch_deps):
        """Mentions returned newest-first: since_id should be the highest ID."""
        from body.x_social import XMentionPoller
        poller = XMentionPoller()

        # Simulate mentions returned in descending order (newest first)
        mentions = [
            {'id': '300', 'author_id': 'u1', 'text': 'newest'},
            {'id': '100', 'author_id': 'u2', 'text': 'oldest'},
            {'id': '200', 'author_id': 'u3', 'text': 'middle'},
        ]
        with patch('body.x_client.fetch_mentions', new_callable=AsyncMock) as mock_fetch, \
             patch('body.x_social.db') as mock_db:
            mock_fetch.return_value = mentions
            mock_db.get_visitor = AsyncMock(return_value=None)
            mock_db.insert_visitor = AsyncMock()
            mock_db.add_visitor_present = AsyncMock()
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()
            await poller._poll_once()

        # since_id should be '300' (the max), not '200' (the last iterated)
        assert poller._since_id == '300'

    @pytest.mark.asyncio
    async def test_since_id_advances_across_polls(self, _patch_deps):
        """since_id from first poll persists and advances in second."""
        from body.x_social import XMentionPoller
        poller = XMentionPoller()
        poller._since_id = '250'  # from a previous poll

        mentions = [
            {'id': '200', 'author_id': 'u1', 'text': 'older than checkpoint'},
        ]
        with patch('body.x_client.fetch_mentions', new_callable=AsyncMock) as mock_fetch, \
             patch('body.x_social.db') as mock_db:
            mock_fetch.return_value = mentions
            mock_db.get_visitor = AsyncMock(return_value=None)
            mock_db.insert_visitor = AsyncMock()
            mock_db.add_visitor_present = AsyncMock()
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()
            await poller._poll_once()

        # since_id should NOT regress from 250 to 200
        assert poller._since_id == '250'
