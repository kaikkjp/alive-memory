"""Tests for body/channels.py — reply routing."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture(autouse=True)
def _patch_db_connection():
    """Mock DB connection for channel router."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value=mock_cursor)

    with patch('body.channels._connection') as mock_connection:
        mock_connection.get_db = AsyncMock(return_value=mock_conn)
        yield mock_connection, mock_conn, mock_cursor


class TestGetVisitorChannel:
    """Test get_visitor_channel lookup."""

    @pytest.mark.asyncio
    async def test_returns_channel_from_db(self, _patch_db_connection):
        """Returns channel from visitors_present table."""
        _, _, mock_cursor = _patch_db_connection
        mock_cursor.fetchone = AsyncMock(return_value=('telegram',))
        from body.channels import get_visitor_channel
        result = await get_visitor_channel('tg_12345')
        assert result == 'telegram'

    @pytest.mark.asyncio
    async def test_defaults_to_web(self, _patch_db_connection):
        """Returns 'web' when no record found."""
        _, _, mock_cursor = _patch_db_connection
        mock_cursor.fetchone = AsyncMock(return_value=None)
        from body.channels import get_visitor_channel
        result = await get_visitor_channel('unknown_visitor')
        assert result == 'web'


class TestRouteReply:
    """Test route_reply dispatching."""

    @pytest.mark.asyncio
    async def test_web_channel_returns_broadcast(self, _patch_db_connection):
        """Web channel returns immediately with broadcast method."""
        from body.channels import route_reply
        result = await route_reply('v1', 'hello', channel='web')
        assert result['routed'] is True
        assert result['channel'] == 'web'
        assert result['method'] == 'broadcast'

    @pytest.mark.asyncio
    async def test_tcp_channel_returns_broadcast(self, _patch_db_connection):
        """TCP channel returns immediately with broadcast method."""
        from body.channels import route_reply
        result = await route_reply('v1', 'hello', channel='tcp')
        assert result['routed'] is True
        assert result['channel'] == 'tcp'

    @pytest.mark.asyncio
    async def test_telegram_channel_calls_send_reply(self, _patch_db_connection):
        """Telegram channel calls body.telegram.send_reply."""
        with patch('body.telegram.send_reply', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {'success': True}
            from body.channels import route_reply
            result = await route_reply('tg_1', 'hi', channel='telegram')
        assert result['routed'] is True
        assert result['channel'] == 'telegram'
        mock_send.assert_called_once_with('tg_1', 'hi', image_path=None)

    @pytest.mark.asyncio
    async def test_x_channel_calls_reply_to_visitor(self, _patch_db_connection):
        """X channel calls body.x_social.reply_to_visitor."""
        with patch('body.x_social.reply_to_visitor', new_callable=AsyncMock) as mock_reply:
            mock_reply.return_value = {'success': True}
            from body.channels import route_reply
            result = await route_reply('x_1', 'hey', channel='x')
        assert result['routed'] is True
        assert result['channel'] == 'x'
        mock_reply.assert_called_once_with('x_1', 'hey')

    @pytest.mark.asyncio
    async def test_telegram_api_failure_returns_routed_false(self, _patch_db_connection):
        """Telegram API returning success=False sets routed=False."""
        with patch('body.telegram.send_reply', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {'success': False, 'error': 'rate limited'}
            from body.channels import route_reply
            result = await route_reply('tg_1', 'hi', channel='telegram')
        assert result['routed'] is False
        assert result['channel'] == 'telegram'

    @pytest.mark.asyncio
    async def test_x_api_failure_returns_routed_false(self, _patch_db_connection):
        """X API returning success=False sets routed=False."""
        with patch('body.x_social.reply_to_visitor', new_callable=AsyncMock) as mock_reply:
            mock_reply.return_value = {'success': False, 'error': 'no tweet context'}
            from body.channels import route_reply
            result = await route_reply('x_1', 'hey', channel='x')
        assert result['routed'] is False
        assert result['channel'] == 'x'

    @pytest.mark.asyncio
    async def test_unknown_channel_returns_error(self, _patch_db_connection):
        """Unknown channel returns routed=False."""
        from body.channels import route_reply
        result = await route_reply('v1', 'hello', channel='smoke_signal')
        assert result['routed'] is False
        assert 'unknown' in result['reason']
