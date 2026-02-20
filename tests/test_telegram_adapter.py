"""Tests for body/telegram.py — Telegram adapter + executors (TASK-069)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models.pipeline import ActionRequest, ActionResult


@pytest.fixture(autouse=True)
def _patch_deps():
    """Mock all external deps for Telegram executors."""
    with patch('body.telegram.clock') as mock_clock, \
         patch('body.telegram.check_rate_limit', new_callable=AsyncMock) as mock_rate, \
         patch('body.telegram.record_action', new_callable=AsyncMock), \
         patch('body.telegram.is_channel_enabled', new_callable=AsyncMock) as mock_chan, \
         patch('body.telegram.db') as mock_db:
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


class TestTgSend:
    """Test execute_tg_send executor."""

    @pytest.mark.asyncio
    async def test_successful_send(self, _patch_deps):
        """Successful send returns message_id."""
        from body.telegram import execute_tg_send
        action = ActionRequest(type='tg_send', detail={'text': 'hello group'})

        with patch('body.tg_client.send_message', new_callable=AsyncMock) as mock_send, \
             patch.dict('os.environ', {'TELEGRAM_GROUP_CHAT_ID': '12345'}):
            mock_send.return_value = {'success': True, 'message_id': 42}
            result = await execute_tg_send(action)

        assert result.success is True
        assert result.payload['message_id'] == 42

    @pytest.mark.asyncio
    async def test_empty_text_fails(self, _patch_deps):
        """Empty text returns error."""
        from body.telegram import execute_tg_send
        action = ActionRequest(type='tg_send', detail={})
        result = await execute_tg_send(action)
        assert result.success is False
        assert 'no message text' in result.error

    @pytest.mark.asyncio
    async def test_channel_disabled_blocks(self, _patch_deps):
        """Disabled telegram channel blocks sending."""
        _patch_deps['channel_enabled'].return_value = False
        from body.telegram import execute_tg_send
        action = ActionRequest(type='tg_send', detail={'text': 'test'})
        result = await execute_tg_send(action)
        assert result.success is False
        assert 'channel disabled' in result.error

    @pytest.mark.asyncio
    async def test_rate_limit_blocks(self, _patch_deps):
        """Rate limit blocks sending."""
        _patch_deps['rate_limit'].return_value = (False, 'hourly limit reached')
        from body.telegram import execute_tg_send
        action = ActionRequest(type='tg_send', detail={'text': 'test'})
        result = await execute_tg_send(action)
        assert result.success is False
        assert 'hourly limit' in result.error


class TestTgSendImage:
    """Test execute_tg_send_image executor."""

    @pytest.mark.asyncio
    async def test_missing_image_path_fails(self, _patch_deps):
        """Missing image_path returns error."""
        from body.telegram import execute_tg_send_image
        action = ActionRequest(type='tg_send_image', detail={'text': 'look'})
        result = await execute_tg_send_image(action)
        assert result.success is False
        assert 'no image_path' in result.error

    @pytest.mark.asyncio
    async def test_successful_image_send(self, _patch_deps):
        """Successful image send returns message_id."""
        from body.telegram import execute_tg_send_image
        action = ActionRequest(type='tg_send_image', detail={
            'text': 'check this',
            'image_path': '/tmp/test.png',
        })

        with patch('body.tg_client.send_photo', new_callable=AsyncMock) as mock_photo, \
             patch.dict('os.environ', {'TELEGRAM_GROUP_CHAT_ID': '12345'}):
            mock_photo.return_value = {'success': True, 'message_id': 43}
            result = await execute_tg_send_image(action)

        assert result.success is True
        assert result.payload['message_id'] == 43


class TestTelegramAdapter:
    """Test TelegramAdapter message handling."""

    @pytest.mark.asyncio
    async def test_handle_message_creates_event(self, _patch_deps):
        """Message handling creates visitor_speech event."""
        from body.telegram import TelegramAdapter

        adapter = TelegramAdapter(group_chat_id='12345')

        # Create mock message
        mock_message = MagicMock()
        mock_message.from_user = MagicMock()
        mock_message.from_user.id = 999
        mock_message.from_user.first_name = 'Test'
        mock_message.from_user.username = 'testuser'
        mock_message.text = 'hello shopkeeper'
        mock_message.message_id = 1
        mock_message.chat = MagicMock()
        mock_message.chat.id = 12345

        mock_db = _patch_deps['db']
        mock_db.get_visitor = AsyncMock(return_value=None)
        mock_db.add_visitor_present = AsyncMock()
        mock_db.update_visitor = AsyncMock()
        mock_db.mark_session_boundary = AsyncMock()
        mock_db.inbox_add = AsyncMock()

        with patch('body.telegram.on_visitor_connect', new_callable=AsyncMock) as mock_connect:
            await adapter._handle_message(mock_message)
            mock_connect.assert_called_once()

        # Should have called append_event
        mock_db.append_event.assert_called_once()
        event = mock_db.append_event.call_args[0][0]
        assert event.event_type == 'visitor_speech'
        assert 'tg_999' in event.source
        assert event.payload['text'] == 'hello shopkeeper'
        assert event.payload['platform'] == 'telegram'
