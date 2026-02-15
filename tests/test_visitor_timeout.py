"""Tests for TASK-017: Unengaged visitor idle timeout.

Verifies:
- Visitors idle beyond VISITOR_IDLE_TIMEOUT are cleaned up
- Engaged visitors are NOT timed out (even if idle)
- Disconnect event is generated for timed-out visitors
- TCP connections are closed on timeout
- Recently active visitors are not timed out
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

from models.state import EngagementState, VisitorPresence
from models.event import Event


# ── _check_visitor_timeouts unit tests ──

class TestVisitorTimeout:
    """Test the idle timeout checker logic."""

    @pytest.fixture
    def server(self):
        """Create a minimal ShopkeeperServer mock for testing."""
        from heartbeat_server import ShopkeeperServer, VISITOR_IDLE_TIMEOUT

        with patch.object(ShopkeeperServer, '__init__', lambda self: None):
            srv = ShopkeeperServer.__new__(ShopkeeperServer)
            srv.connections = {}
            srv.heartbeat = MagicMock()
            srv.heartbeat.unsubscribe_cycle_logs = MagicMock()
            srv._send = AsyncMock()
            return srv

    @pytest.mark.asyncio
    async def test_idle_unengaged_visitor_cleaned_up(self, server):
        """Visitor idle > 5 min with no engagement is removed."""
        from heartbeat_server import VISITOR_IDLE_TIMEOUT

        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=VISITOR_IDLE_TIMEOUT + 60)

        idle_visitor = VisitorPresence(
            visitor_id='v_idle',
            status='browsing',
            entered_at=old_time,
            last_activity=old_time,
            connection_type='tcp',
        )
        engagement = EngagementState(status='none', visitor_id=None)

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock) as mock_disconnect:
            mock_db.get_visitors_present = AsyncMock(return_value=[idle_visitor])
            mock_db.get_engagement_state = AsyncMock(return_value=engagement)
            mock_db.remove_visitor_present = AsyncMock()
            mock_clock.now.return_value = now

            await server._check_visitor_timeouts()

            mock_db.remove_visitor_present.assert_called_once_with('v_idle')
            mock_disconnect.assert_called_once()
            event = mock_disconnect.call_args[0][0]
            assert event.event_type == 'visitor_disconnect'
            assert 'idle_timeout' in str(event.payload)

    @pytest.mark.asyncio
    async def test_engaged_visitor_not_timed_out(self, server):
        """Visitor the shopkeeper is talking to is never timed out."""
        from heartbeat_server import VISITOR_IDLE_TIMEOUT

        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=VISITOR_IDLE_TIMEOUT + 120)

        engaged_visitor = VisitorPresence(
            visitor_id='v_engaged',
            status='in_conversation',
            entered_at=old_time,
            last_activity=old_time,
            connection_type='tcp',
        )
        engagement = EngagementState(
            status='engaged', visitor_id='v_engaged', turn_count=3
        )

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock) as mock_disconnect:
            mock_db.get_visitors_present = AsyncMock(return_value=[engaged_visitor])
            mock_db.get_engagement_state = AsyncMock(return_value=engagement)
            mock_db.remove_visitor_present = AsyncMock()
            mock_clock.now.return_value = now

            await server._check_visitor_timeouts()

            mock_db.remove_visitor_present.assert_not_called()
            mock_disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_recently_active_visitor_not_timed_out(self, server):
        """Visitor who sent a message recently is not timed out."""
        from heartbeat_server import VISITOR_IDLE_TIMEOUT

        now = datetime.now(timezone.utc)
        recent_time = now - timedelta(seconds=60)  # 1 min ago

        active_visitor = VisitorPresence(
            visitor_id='v_active',
            status='browsing',
            entered_at=now - timedelta(seconds=600),
            last_activity=recent_time,
            connection_type='tcp',
        )
        engagement = EngagementState(status='none', visitor_id=None)

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock) as mock_disconnect:
            mock_db.get_visitors_present = AsyncMock(return_value=[active_visitor])
            mock_db.get_engagement_state = AsyncMock(return_value=engagement)
            mock_db.remove_visitor_present = AsyncMock()
            mock_clock.now.return_value = now

            await server._check_visitor_timeouts()

            mock_db.remove_visitor_present.assert_not_called()
            mock_disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_tcp_connection_closed_on_timeout(self, server):
        """TCP writer is closed when a visitor times out."""
        from heartbeat_server import VISITOR_IDLE_TIMEOUT

        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=VISITOR_IDLE_TIMEOUT + 30)

        idle_visitor = VisitorPresence(
            visitor_id='v_tcp',
            status='browsing',
            entered_at=old_time,
            last_activity=old_time,
            connection_type='tcp',
        )
        engagement = EngagementState(status='none', visitor_id=None)

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        server.connections['v_tcp'] = mock_writer

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock):
            mock_db.get_visitors_present = AsyncMock(return_value=[idle_visitor])
            mock_db.get_engagement_state = AsyncMock(return_value=engagement)
            mock_db.remove_visitor_present = AsyncMock()
            mock_clock.now.return_value = now

            await server._check_visitor_timeouts()

            # TCP connection should be closed
            mock_writer.close.assert_called_once()
            # Visitor removed from connections dict
            assert 'v_tcp' not in server.connections
            # Farewell message sent before close
            server._send.assert_called()

    @pytest.mark.asyncio
    async def test_multiple_visitors_selective_timeout(self, server):
        """With multiple visitors, only idle unengaged ones are cleaned up."""
        from heartbeat_server import VISITOR_IDLE_TIMEOUT

        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=VISITOR_IDLE_TIMEOUT + 60)
        recent_time = now - timedelta(seconds=30)

        visitors = [
            VisitorPresence(
                visitor_id='v_idle', status='browsing',
                entered_at=old_time, last_activity=old_time,
                connection_type='tcp',
            ),
            VisitorPresence(
                visitor_id='v_active', status='browsing',
                entered_at=old_time, last_activity=recent_time,
                connection_type='websocket',
            ),
            VisitorPresence(
                visitor_id='v_engaged', status='in_conversation',
                entered_at=old_time, last_activity=old_time,
                connection_type='tcp',
            ),
        ]
        engagement = EngagementState(
            status='engaged', visitor_id='v_engaged', turn_count=2
        )

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock) as mock_disconnect:
            mock_db.get_visitors_present = AsyncMock(return_value=visitors)
            mock_db.get_engagement_state = AsyncMock(return_value=engagement)
            mock_db.remove_visitor_present = AsyncMock()
            mock_clock.now.return_value = now

            await server._check_visitor_timeouts()

            # Only v_idle should be removed
            mock_db.remove_visitor_present.assert_called_once_with('v_idle')
            mock_disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_last_activity_none_falls_back_to_entered_at(self, server):
        """When last_activity is None, timeout uses entered_at instead."""
        from heartbeat_server import VISITOR_IDLE_TIMEOUT

        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=VISITOR_IDLE_TIMEOUT + 60)

        visitor = VisitorPresence(
            visitor_id='v_no_activity',
            status='browsing',
            entered_at=old_time,
            last_activity=None,  # never sent a message
            connection_type='tcp',
        )
        engagement = EngagementState(status='none', visitor_id=None)

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock):
            mock_db.get_visitors_present = AsyncMock(return_value=[visitor])
            mock_db.get_engagement_state = AsyncMock(return_value=engagement)
            mock_db.remove_visitor_present = AsyncMock()
            mock_clock.now.return_value = now

            await server._check_visitor_timeouts()

            mock_db.remove_visitor_present.assert_called_once_with('v_no_activity')

    @pytest.mark.asyncio
    async def test_both_timestamps_none_skipped(self, server):
        """Visitor with no timestamps at all is silently skipped (not crashed)."""
        visitor = VisitorPresence(
            visitor_id='v_broken',
            status='browsing',
            entered_at=None,
            last_activity=None,
            connection_type='tcp',
        )
        engagement = EngagementState(status='none', visitor_id=None)

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock) as mock_disconnect:
            mock_db.get_visitors_present = AsyncMock(return_value=[visitor])
            mock_db.get_engagement_state = AsyncMock(return_value=engagement)
            mock_db.remove_visitor_present = AsyncMock()
            mock_clock.now.return_value = datetime.now(timezone.utc)

            await server._check_visitor_timeouts()

            # Should not crash, but also not clean up (no timestamp to compare)
            mock_db.remove_visitor_present.assert_not_called()
            mock_disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_visitors_no_errors(self, server):
        """Empty shop produces no errors."""
        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock:
            mock_db.get_visitors_present = AsyncMock(return_value=[])
            mock_clock.now.return_value = datetime.now(timezone.utc)

            # Should return without calling get_engagement_state
            await server._check_visitor_timeouts()
            mock_db.get_engagement_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_string_timestamp_parsed(self, server):
        """last_activity stored as ISO string is parsed correctly."""
        from heartbeat_server import VISITOR_IDLE_TIMEOUT

        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(seconds=VISITOR_IDLE_TIMEOUT + 60)).isoformat()

        visitor = VisitorPresence(
            visitor_id='v_str',
            status='browsing',
            entered_at=old_time,
            last_activity=old_time,  # string, not datetime
            connection_type='websocket',
        )
        engagement = EngagementState(status='none', visitor_id=None)

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock):
            mock_db.get_visitors_present = AsyncMock(return_value=[visitor])
            mock_db.get_engagement_state = AsyncMock(return_value=engagement)
            mock_db.remove_visitor_present = AsyncMock()
            mock_clock.now.return_value = now

            await server._check_visitor_timeouts()

            mock_db.remove_visitor_present.assert_called_once_with('v_str')


class TestVisitorIdleTimeoutConstant:
    """Verify the timeout constant exists and is reasonable."""

    def test_timeout_is_300_seconds(self):
        from heartbeat_server import VISITOR_IDLE_TIMEOUT
        assert VISITOR_IDLE_TIMEOUT == 300
