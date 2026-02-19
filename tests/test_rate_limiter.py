"""Tests for body/rate_limiter.py — sliding window enforcement."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta


@pytest.fixture(autouse=True)
def _patch_db():
    """Mock DB access for rate limiter."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value=mock_cursor)

    with patch('body.rate_limiter._connection') as mock_connection:
        mock_connection.get_db = AsyncMock(return_value=mock_conn)
        mock_connection._exec_write = AsyncMock()
        yield mock_connection, mock_conn, mock_cursor


@pytest.fixture(autouse=True)
def _patch_clock():
    with patch('body.rate_limiter.clock') as mock_clock:
        mock_clock.now_utc.return_value = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        yield mock_clock


class TestCheckRateLimit:
    """Test check_rate_limit function."""

    @pytest.mark.asyncio
    async def test_unknown_action_allowed(self):
        """Actions not in RATE_LIMITS are always allowed."""
        from body.rate_limiter import check_rate_limit
        allowed, reason = await check_rate_limit('unknown_action')
        assert allowed is True
        assert reason == ''

    @pytest.mark.asyncio
    async def test_allowed_when_no_history(self, _patch_db):
        """Action allowed when no prior history."""
        from body.rate_limiter import check_rate_limit
        allowed, reason = await check_rate_limit('browse_web')
        assert allowed is True

    @pytest.mark.asyncio
    async def test_cooldown_blocks(self, _patch_db, _patch_clock):
        """Action blocked when still in cooldown."""
        _, mock_conn, mock_cursor = _patch_db
        # First call: _get_last_action_timestamp — return 60s ago
        now = _patch_clock.now_utc.return_value
        recent_ts = (now - timedelta(seconds=60)).isoformat()
        mock_cursor.fetchone = AsyncMock(
            side_effect=[(recent_ts,), (0,), (0,)]  # last_ts, hourly, daily
        )

        from body.rate_limiter import check_rate_limit
        allowed, reason = await check_rate_limit('browse_web')
        assert allowed is False
        assert 'cooldown' in reason

    @pytest.mark.asyncio
    async def test_hourly_limit_blocks(self, _patch_db, _patch_clock):
        """Action blocked when hourly limit reached."""
        _, mock_conn, mock_cursor = _patch_db
        mock_cursor.fetchone = AsyncMock(
            side_effect=[None, (20,), (0,)]  # no last_ts, hourly at limit, daily ok
        )

        from body.rate_limiter import check_rate_limit
        allowed, reason = await check_rate_limit('browse_web')
        assert allowed is False
        assert 'hourly' in reason


class TestRecordAction:
    """Test record_action function."""

    @pytest.mark.asyncio
    async def test_record_inserts_row(self, _patch_db):
        """record_action writes to external_action_log."""
        mock_connection, _, _ = _patch_db
        from body.rate_limiter import record_action
        await record_action('post_x', success=True, channel='x')
        mock_connection._exec_write.assert_called_once()
        call_args = mock_connection._exec_write.call_args
        assert 'external_action_log' in call_args[0][0]


class TestChannelEnabled:
    """Test is_channel_enabled function."""

    @pytest.mark.asyncio
    async def test_enabled_channel(self, _patch_db):
        """Enabled channel returns True."""
        _, mock_conn, mock_cursor = _patch_db
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        from body.rate_limiter import is_channel_enabled
        result = await is_channel_enabled('web')
        assert result is True

    @pytest.mark.asyncio
    async def test_disabled_channel(self, _patch_db):
        """Disabled channel returns False."""
        _, mock_conn, mock_cursor = _patch_db
        mock_cursor.fetchone = AsyncMock(return_value=(0,))
        from body.rate_limiter import is_channel_enabled
        result = await is_channel_enabled('x')
        assert result is False

    @pytest.mark.asyncio
    async def test_unknown_channel_disabled(self, _patch_db):
        """Unknown channel returns False."""
        _, mock_conn, mock_cursor = _patch_db
        mock_cursor.fetchone = AsyncMock(return_value=None)
        from body.rate_limiter import is_channel_enabled
        result = await is_channel_enabled('carrier_pigeon')
        assert result is False
