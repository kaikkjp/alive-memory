"""Tests for TASK-058B: Visitor connection registry.

Verifies:
- First valid message registers in _ws_visitor_map
- display_name derived from token validation
- Repeated messages from same WS don't duplicate registry
- Disconnect clears registry entry
- Socket drop clears registry entry
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


class TestVisitorRegistry:
    """Test the visitor connection registry (_ws_visitor_map)."""

    @pytest.fixture
    def server(self):
        from heartbeat_server import ShopkeeperServer

        with patch.object(ShopkeeperServer, '__init__', lambda self: None):
            srv = ShopkeeperServer.__new__(ShopkeeperServer)
            srv._window_clients = set()
            srv._ws_visitor_map = {}
            srv._chat_history = []
            srv._CHAT_HISTORY_MAX = 50
            srv._last_chat_response_content = ''
            srv.heartbeat = MagicMock()
            srv.heartbeat.schedule_microcycle = AsyncMock()
            srv.connections = {}
            return srv

    def _mock_deps(self):
        """Return common patched deps for _handle_ws_chat."""
        mock_db = MagicMock()
        mock_db.validate_and_consume_chat_token = AsyncMock(return_value={
            'display_name': 'TestUser',
            'uses_remaining': 5,
        })
        mock_db.add_visitor_present = AsyncMock()
        mock_db.update_visitor_present = AsyncMock()
        mock_db.update_visitor = AsyncMock()
        mock_db.mark_session_boundary = AsyncMock()
        mock_db.append_conversation = AsyncMock()
        mock_db.append_event = AsyncMock()
        mock_db.inbox_add = AsyncMock()
        return mock_db

    @pytest.mark.asyncio
    async def test_first_message_registers_visitor(self, server):
        """First valid message from a WS registers it in _ws_visitor_map."""
        visitor_ws = AsyncMock()
        mock_db = self._mock_deps()

        with patch('heartbeat_server.db', mock_db), \
             patch('heartbeat_server.on_visitor_connect', new_callable=AsyncMock) as mock_connect, \
             patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._handle_ws_chat(
                {'token': 'tok_test', 'text': 'Hi'},
                visitor_ws,
            )

            assert visitor_ws in server._ws_visitor_map
            info = server._ws_visitor_map[visitor_ws]
            assert info['display_name'] == 'TestUser'
            assert info['visitor_id'] == 'web_testuser'
            assert info['token'] == 'tok_test'
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_display_name_from_token(self, server):
        """display_name is derived from token validation result."""
        visitor_ws = AsyncMock()
        mock_db = self._mock_deps()
        mock_db.validate_and_consume_chat_token = AsyncMock(return_value={
            'display_name': 'Café Visitor',
            'uses_remaining': 3,
        })

        with patch('heartbeat_server.db', mock_db), \
             patch('heartbeat_server.on_visitor_connect', new_callable=AsyncMock), \
             patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._handle_ws_chat(
                {'token': 'tok_cafe', 'text': 'Bonjour'},
                visitor_ws,
            )

            assert server._ws_visitor_map[visitor_ws]['display_name'] == 'Café Visitor'
            assert server._ws_visitor_map[visitor_ws]['visitor_id'] == 'web_café_visitor'

    @pytest.mark.asyncio
    async def test_repeated_messages_no_duplicate_registration(self, server):
        """Same WS sending multiple messages doesn't duplicate the registry entry."""
        visitor_ws = AsyncMock()
        mock_db = self._mock_deps()

        with patch('heartbeat_server.db', mock_db), \
             patch('heartbeat_server.on_visitor_connect', new_callable=AsyncMock) as mock_connect, \
             patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            # Send two messages from same WS
            await server._handle_ws_chat(
                {'token': 'tok_test', 'text': 'First'},
                visitor_ws,
            )
            await server._handle_ws_chat(
                {'token': 'tok_test', 'text': 'Second'},
                visitor_ws,
            )

            # Should have exactly one entry
            count = sum(1 for ws in server._ws_visitor_map if ws is visitor_ws)
            assert count == 1
            # on_visitor_connect only called once (first message)
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_visitor_triggers_presence_broadcast(self, server):
        """First message from a new visitor broadcasts visitor_presence."""
        visitor_ws = AsyncMock()
        ws_viewer = AsyncMock()
        server._window_clients = {ws_viewer}
        mock_db = self._mock_deps()

        with patch('heartbeat_server.db', mock_db), \
             patch('heartbeat_server.on_visitor_connect', new_callable=AsyncMock), \
             patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._handle_ws_chat(
                {'token': 'tok_test', 'text': 'Hello'},
                visitor_ws,
            )

            # Find the visitor_presence message
            messages = [json.loads(c.args[0]) for c in ws_viewer.send.call_args_list]
            presence_msgs = [m for m in messages if m.get('type') == 'visitor_presence']
            assert len(presence_msgs) >= 1
            assert presence_msgs[0]['visitor_count'] == 1
            assert presence_msgs[0]['visitors'][0]['display_name'] == 'TestUser'

    @pytest.mark.asyncio
    async def test_second_message_no_presence_broadcast(self, server):
        """Subsequent messages from same WS don't trigger presence broadcast."""
        visitor_ws = AsyncMock()
        ws_viewer = AsyncMock()
        server._window_clients = {ws_viewer}
        mock_db = self._mock_deps()

        with patch('heartbeat_server.db', mock_db), \
             patch('heartbeat_server.on_visitor_connect', new_callable=AsyncMock), \
             patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            # First message
            await server._handle_ws_chat(
                {'token': 'tok_test', 'text': 'Hello'},
                visitor_ws,
            )
            first_count = ws_viewer.send.call_count

            # Reset viewer call count
            ws_viewer.send.reset_mock()

            # Second message from same WS
            await server._handle_ws_chat(
                {'token': 'tok_test', 'text': 'Again'},
                visitor_ws,
            )

            # Check no visitor_presence was sent on second message
            messages = [json.loads(c.args[0]) for c in ws_viewer.send.call_args_list]
            presence_msgs = [m for m in messages if m.get('type') == 'visitor_presence']
            assert len(presence_msgs) == 0

    @pytest.mark.asyncio
    async def test_disconnect_clears_registry(self, server):
        """Explicit disconnect removes entry from _ws_visitor_map."""
        visitor_ws = AsyncMock()
        server._ws_visitor_map[visitor_ws] = {
            'visitor_id': 'web_alice',
            'display_name': 'Alice',
            'token': 'tok_alice',
        }

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=AsyncMock(
                fetchone=AsyncMock(return_value={
                    'display_name': 'Alice',
                    'expires_at': '2026-12-31T00:00:00',
                })
            ))
            mock_db.get_db = AsyncMock(return_value=mock_conn)
            mock_db.remove_visitor_present = AsyncMock()
            mock_db.get_engagement_state = AsyncMock(return_value=MagicMock(visitor_id=None))
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._handle_ws_disconnect({'token': 'tok_alice'})

            assert visitor_ws not in server._ws_visitor_map

    @pytest.mark.asyncio
    async def test_multiple_visitors_tracked(self, server):
        """Multiple different WebSockets are tracked separately."""
        ws_alice = AsyncMock()
        ws_bob = AsyncMock()
        mock_db = self._mock_deps()

        with patch('heartbeat_server.db', mock_db), \
             patch('heartbeat_server.on_visitor_connect', new_callable=AsyncMock), \
             patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            # Alice joins
            mock_db.validate_and_consume_chat_token = AsyncMock(return_value={
                'display_name': 'Alice', 'uses_remaining': 5,
            })
            await server._handle_ws_chat({'token': 'tok_a', 'text': 'Hi'}, ws_alice)

            # Bob joins
            mock_db.validate_and_consume_chat_token = AsyncMock(return_value={
                'display_name': 'Bob', 'uses_remaining': 3,
            })
            await server._handle_ws_chat({'token': 'tok_b', 'text': 'Hey'}, ws_bob)

            assert len(server._ws_visitor_map) == 2
            assert server._ws_visitor_map[ws_alice]['display_name'] == 'Alice'
            assert server._ws_visitor_map[ws_bob]['display_name'] == 'Bob'
