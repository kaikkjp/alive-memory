"""Tests for body/telegram.py — Telegram adapter + executors (TASK-069)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models.pipeline import ActionRequest, ActionResult


@pytest.fixture(autouse=True)
def _patch_deps():
    """Mock all external deps for Telegram executors."""
    with patch('body.telegram.clock') as mock_clock, \
         patch('body.telegram.get_limiter_decision', new_callable=AsyncMock) as mock_rate, \
         patch('body.telegram.record_action', new_callable=AsyncMock), \
         patch('body.telegram.is_channel_enabled', new_callable=AsyncMock) as mock_chan, \
         patch('body.telegram.db') as mock_db:
        mock_clock.now_utc.return_value = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_rate.return_value = {
            'allowed': True,
            'reason': '',
            'limiter_decision': 'allow',
            'cooldown_state': 'ready',
            'rate_limit_remaining': 1,
        }
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
        _patch_deps['rate_limit'].return_value = {
            'allowed': False,
            'reason': 'hourly limit reached',
            'limiter_decision': 'deny:hourly_limit',
            'cooldown_state': 'ready',
            'rate_limit_remaining': 0,
        }
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
        """First message from new visitor fires connect + boundary + speech event."""
        from body.telegram import TelegramAdapter
        from models.state import EngagementState

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
        # Not engaged — first message should fire visitor_connect
        mock_db.get_engagement_state = AsyncMock(
            return_value=EngagementState(status='none'))
        mock_db.get_visitor = AsyncMock(return_value=None)
        mock_db.add_visitor_present = AsyncMock()
        mock_db.update_visitor = AsyncMock()
        mock_db.mark_session_boundary = AsyncMock()
        mock_db.inbox_add = AsyncMock()

        with patch('body.telegram.on_visitor_connect', new_callable=AsyncMock) as mock_connect:
            await adapter._handle_message(mock_message)
            mock_connect.assert_called_once()

        # Session boundary should fire on first message
        mock_db.mark_session_boundary.assert_called_once()

        # Should have called append_event
        mock_db.append_event.assert_called_once()
        event = mock_db.append_event.call_args[0][0]
        assert event.event_type == 'visitor_speech'
        assert 'tg_999' in event.source
        assert event.payload['text'] == 'hello shopkeeper'
        assert event.payload['platform'] == 'telegram'

    @pytest.mark.asyncio
    async def test_handle_message_skips_connect_when_engaged(self, _patch_deps):
        """Subsequent messages during engagement skip connect + boundary."""
        from body.telegram import TelegramAdapter
        from models.state import EngagementState

        adapter = TelegramAdapter(group_chat_id='12345')

        mock_message = MagicMock()
        mock_message.from_user = MagicMock()
        mock_message.from_user.id = 999
        mock_message.from_user.first_name = 'Test'
        mock_message.from_user.username = 'testuser'
        mock_message.text = 'tell me more'
        mock_message.message_id = 2
        mock_message.chat = MagicMock()
        mock_message.chat.id = 12345

        mock_db = _patch_deps['db']
        # Already engaged with this visitor — should skip connect + boundary
        mock_db.get_engagement_state = AsyncMock(
            return_value=EngagementState(status='engaged', visitor_id='tg_999'))
        mock_db.add_visitor_present = AsyncMock()
        mock_db.update_visitor = AsyncMock()
        mock_db.mark_session_boundary = AsyncMock()
        mock_db.inbox_add = AsyncMock()

        with patch('body.telegram.on_visitor_connect', new_callable=AsyncMock) as mock_connect:
            await adapter._handle_message(mock_message)
            # Should NOT fire connect on subsequent message
            mock_connect.assert_not_called()

        # Session boundary should NOT fire during engagement
        mock_db.mark_session_boundary.assert_not_called()

        # Speech event still fires
        mock_db.append_event.assert_called_once()
        event = mock_db.append_event.call_args[0][0]
        assert event.event_type == 'visitor_speech'


class TestConnectRaceGuard:
    """Test that concurrent messages don't fire connect twice."""

    @pytest.mark.asyncio
    async def test_two_messages_same_visitor_one_connect(self, _patch_deps):
        """Two back-to-back messages from same visitor should only connect once."""
        from body.telegram import TelegramAdapter
        from models.state import EngagementState

        adapter = TelegramAdapter(group_chat_id='12345')

        def make_msg(text, msg_id):
            m = MagicMock()
            m.from_user = MagicMock()
            m.from_user.id = 777
            m.from_user.first_name = 'Racer'
            m.from_user.username = 'racer'
            m.text = text
            m.message_id = msg_id
            m.chat = MagicMock()
            m.chat.id = 12345
            return m

        mock_db = _patch_deps['db']
        # Both calls see engagement as "none" (race window)
        mock_db.get_engagement_state = AsyncMock(
            return_value=EngagementState(status='none', visitor_id=None))
        mock_db.add_visitor_present = AsyncMock()
        mock_db.update_visitor = AsyncMock()
        mock_db.mark_session_boundary = AsyncMock()
        mock_db.inbox_add = AsyncMock()

        with patch('body.telegram.on_visitor_connect', new_callable=AsyncMock) as mock_connect:
            await adapter._handle_message(make_msg('first', 1))
            await adapter._handle_message(make_msg('second', 2))

            # connect should fire exactly once despite both seeing "none"
            assert mock_connect.call_count == 1

        # boundary should also fire exactly once
        assert mock_db.mark_session_boundary.call_count == 1

    @pytest.mark.asyncio
    async def test_three_messages_same_batch_one_connect(self, _patch_deps):
        """Three messages in same batch should only connect once."""
        from body.telegram import TelegramAdapter
        from models.state import EngagementState

        adapter = TelegramAdapter(group_chat_id='12345')

        def make_msg(text, msg_id):
            m = MagicMock()
            m.from_user = MagicMock()
            m.from_user.id = 777
            m.from_user.first_name = 'Racer'
            m.from_user.username = 'racer'
            m.text = text
            m.message_id = msg_id
            m.chat = MagicMock()
            m.chat.id = 12345
            return m

        mock_db = _patch_deps['db']
        mock_db.get_engagement_state = AsyncMock(
            return_value=EngagementState(status='none', visitor_id=None))
        mock_db.add_visitor_present = AsyncMock()
        mock_db.update_visitor = AsyncMock()
        mock_db.mark_session_boundary = AsyncMock()
        mock_db.inbox_add = AsyncMock()

        with patch('body.telegram.on_visitor_connect', new_callable=AsyncMock) as mock_connect:
            await adapter._handle_message(make_msg('one', 1))
            await adapter._handle_message(make_msg('two', 2))
            await adapter._handle_message(make_msg('three', 3))

            # connect fires exactly once — guard blocks msg 2 and 3
            assert mock_connect.call_count == 1

        assert mock_db.mark_session_boundary.call_count == 1

    @pytest.mark.asyncio
    async def test_guard_clears_on_engaged_then_new_visit(self, _patch_deps):
        """Guard clears when engagement catches up; new visit re-connects."""
        from body.telegram import TelegramAdapter
        from models.state import EngagementState

        adapter = TelegramAdapter(group_chat_id='12345')

        def make_msg(text, msg_id):
            m = MagicMock()
            m.from_user = MagicMock()
            m.from_user.id = 777
            m.from_user.first_name = 'Visitor'
            m.from_user.username = 'visitor'
            m.text = text
            m.message_id = msg_id
            m.chat = MagicMock()
            m.chat.id = 12345
            return m

        mock_db = _patch_deps['db']
        mock_db.add_visitor_present = AsyncMock()
        mock_db.update_visitor = AsyncMock()
        mock_db.mark_session_boundary = AsyncMock()
        mock_db.inbox_add = AsyncMock()

        with patch('body.telegram.on_visitor_connect', new_callable=AsyncMock) as mock_connect:
            # Visit 1: not engaged -> connect fires
            mock_db.get_engagement_state = AsyncMock(
                return_value=EngagementState(status='none', visitor_id=None))
            await adapter._handle_message(make_msg('hello', 1))
            assert mock_connect.call_count == 1
            assert 'tg_777' in adapter._connecting

            # Engagement catches up -> guard clears
            mock_db.get_engagement_state = AsyncMock(
                return_value=EngagementState(status='engaged', visitor_id='tg_777'))
            await adapter._handle_message(make_msg('follow up', 2))
            assert 'tg_777' not in adapter._connecting

            # Visit 2: visitor left and returned (engagement back to none)
            mock_db.get_engagement_state = AsyncMock(
                return_value=EngagementState(status='none', visitor_id=None))
            await adapter._handle_message(make_msg('im back', 3))
            # Connect should fire again for the new visit
            assert mock_connect.call_count == 2

    @pytest.mark.asyncio
    async def test_connect_failure_clears_guard(self, _patch_deps):
        """If on_visitor_connect raises, guard must clear so retry is possible."""
        from body.telegram import TelegramAdapter
        from models.state import EngagementState

        adapter = TelegramAdapter(group_chat_id='12345')

        def make_msg(text, msg_id):
            m = MagicMock()
            m.from_user = MagicMock()
            m.from_user.id = 888
            m.from_user.first_name = 'Flaky'
            m.from_user.username = 'flaky'
            m.text = text
            m.message_id = msg_id
            m.chat = MagicMock()
            m.chat.id = 12345
            return m

        mock_db = _patch_deps['db']
        mock_db.get_engagement_state = AsyncMock(
            return_value=EngagementState(status='none', visitor_id=None))
        mock_db.add_visitor_present = AsyncMock()
        mock_db.update_visitor = AsyncMock()
        mock_db.mark_session_boundary = AsyncMock()
        mock_db.inbox_add = AsyncMock()

        with patch('body.telegram.on_visitor_connect', new_callable=AsyncMock) as mock_connect:
            # First call raises — guard must clear
            mock_connect.side_effect = [RuntimeError('transient'), None]

            with pytest.raises(RuntimeError):
                await adapter._handle_message(make_msg('attempt1', 1))

            # Guard should be cleared after failure
            assert 'tg_888' not in adapter._connecting

            # Retry should succeed — connect fires again
            await adapter._handle_message(make_msg('attempt2', 2))
            assert mock_connect.call_count == 2



class TestTraitCooldownReset:
    """Test that trait cooldown resets on session boundary."""

    def test_cooldown_clears_on_session_start(self):
        """clear_trait_cooldown removes entries for the visitor."""
        from pipeline.hippocampus_write import (
            _recent_traits, _trait_is_duplicate, clear_trait_cooldown,
        )
        _recent_traits.clear()

        # First write succeeds
        assert not _trait_is_duplicate('v1', 'interests', 'topic', 'cats')
        # Duplicate blocked
        assert _trait_is_duplicate('v1', 'interests', 'topic', 'cats')

        # Simulate session restart
        clear_trait_cooldown('v1')

        # Same trait now allowed again
        assert not _trait_is_duplicate('v1', 'interests', 'topic', 'cats')

    def test_cooldown_clear_is_visitor_scoped(self):
        """Clearing one visitor's cooldown doesn't affect another."""
        from pipeline.hippocampus_write import (
            _recent_traits, _trait_is_duplicate, clear_trait_cooldown,
        )
        _recent_traits.clear()

        _trait_is_duplicate('v1', 'interests', 'topic', 'cats')
        _trait_is_duplicate('v2', 'interests', 'topic', 'dogs')

        clear_trait_cooldown('v1')

        # v1 cleared, v2 still blocked
        assert not _trait_is_duplicate('v1', 'interests', 'topic', 'cats')
        assert _trait_is_duplicate('v2', 'interests', 'topic', 'dogs')
