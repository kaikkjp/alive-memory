"""Tests for TASK-058B: Broadcast WebSocket room.

Verifies:
- _handle_ws_chat broadcasts chat_message to all window clients
- _on_stage('dialogue') broadcasts chat_response
- Dedup suppresses current_thought in scene_update after chat_response
- Disconnect removes from _window_clients and _ws_visitor_map
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


class TestBroadcastChat:
    """Test that visitor messages are broadcast to all window clients."""

    @pytest.fixture
    def server(self):
        """Create a minimal ShopkeeperServer mock."""
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

    @pytest.mark.asyncio
    async def test_chat_broadcasts_to_all_window_clients(self, server):
        """Visitor chat message is broadcast to all connected window viewers."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        server._window_clients = {ws1, ws2}

        visitor_ws = AsyncMock()
        visitor_ws.send = AsyncMock()

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock:
            mock_db.validate_and_consume_chat_token = AsyncMock(return_value={
                'display_name': 'Alice',
                'uses_remaining': 5,
            })
            mock_db.add_visitor_present = AsyncMock()
            mock_db.update_visitor_present = AsyncMock()
            mock_db.append_conversation = AsyncMock()
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._handle_ws_chat(
                {'token': 'tok_abc', 'text': 'Hello shopkeeper!'},
                visitor_ws,
            )

            # Both window clients should have received messages
            # (chat_message + text_fragment = 2 broadcasts each)
            assert ws1.send.call_count >= 1
            assert ws2.send.call_count >= 1

            # Check that a chat_message was broadcast
            messages_sent = [json.loads(c.args[0]) for c in ws1.send.call_args_list]
            chat_msgs = [m for m in messages_sent if m.get('type') == 'chat_message']
            assert len(chat_msgs) == 1
            assert chat_msgs[0]['sender'] == 'Alice'
            assert chat_msgs[0]['content'] == 'Hello shopkeeper!'
            assert chat_msgs[0]['sender_type'] == 'visitor'

    @pytest.mark.asyncio
    async def test_chat_appends_to_history(self, server):
        """Visitor chat message is appended to _chat_history."""
        visitor_ws = AsyncMock()

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock:
            mock_db.validate_and_consume_chat_token = AsyncMock(return_value={
                'display_name': 'Bob',
                'uses_remaining': 3,
            })
            mock_db.add_visitor_present = AsyncMock()
            mock_db.update_visitor_present = AsyncMock()
            mock_db.append_conversation = AsyncMock()
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._handle_ws_chat(
                {'token': 'tok_bob', 'text': 'Nice day'},
                visitor_ws,
            )

            assert len(server._chat_history) == 1
            assert server._chat_history[0]['type'] == 'chat_message'
            assert server._chat_history[0]['content'] == 'Nice day'

    @pytest.mark.asyncio
    async def test_invalid_token_not_broadcast(self, server):
        """Invalid token → chat_error to sender, no broadcast."""
        visitor_ws = AsyncMock()
        ws1 = AsyncMock()
        server._window_clients = {ws1}

        with patch('heartbeat_server.db') as mock_db:
            mock_db.validate_and_consume_chat_token = AsyncMock(return_value=None)

            await server._handle_ws_chat(
                {'token': 'bad_tok', 'text': 'Hello'},
                visitor_ws,
            )

            # Sender should get chat_error
            visitor_ws.send.assert_called_once()
            err = json.loads(visitor_ws.send.call_args[0][0])
            assert err['type'] == 'chat_error'

            # Window clients should NOT receive anything
            ws1.send.assert_not_called()


class TestBroadcastDialogue:
    """Test that shopkeeper dialogue is broadcast as chat_response."""

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
            srv.connections = {}
            return srv

    @pytest.mark.asyncio
    async def test_dialogue_broadcasts_chat_response(self, server):
        """_on_stage('dialogue') sends chat_response to window clients."""
        ws1 = AsyncMock()
        server._window_clients = {ws1}

        with patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._on_stage('dialogue', {
                'dialogue': 'Welcome to my shop.',
                'expression': 'smiling',
            })

            assert ws1.send.call_count == 1
            msg = json.loads(ws1.send.call_args[0][0])
            assert msg['type'] == 'chat_response'
            assert msg['content'] == 'Welcome to my shop.'
            assert msg['expression'] == 'smiling'

    @pytest.mark.asyncio
    async def test_dialogue_appends_to_chat_history(self, server):
        """Shopkeeper dialogue is added to chat history buffer."""
        with patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._on_stage('dialogue', {
                'dialogue': 'How may I help you?',
                'expression': 'curious',
            })

            assert len(server._chat_history) == 1
            assert server._chat_history[0]['content'] == 'How may I help you?'


class TestDedup:
    """Test dedup logic in _broadcast_to_window."""

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
            return srv

    @pytest.mark.asyncio
    async def test_dedup_suppresses_matching_current_thought(self, server):
        """scene_update.current_thought is cleared if it matches last chat_response."""
        ws1 = AsyncMock()
        server._window_clients = {ws1}

        # First broadcast a chat_response
        await server._broadcast_to_window({
            'type': 'chat_response',
            'content': 'Welcome to my shop.',
            'expression': 'smiling',
            'timestamp': '2026-01-01T00:00:00+00:00',
        })

        # Now broadcast a scene_update with matching current_thought
        await server._broadcast_to_window({
            'type': 'scene_update',
            'text': {
                'current_thought': 'Welcome to my shop.',
                'activity_label': 'Talking',
            },
            'layers': {},
            'state': {},
            'timestamp': '2026-01-01T00:00:01+00:00',
        })

        assert ws1.send.call_count == 2
        scene_msg = json.loads(ws1.send.call_args_list[1][0][0])
        # current_thought should be cleared by dedup
        assert scene_msg['text']['current_thought'] == ''

    @pytest.mark.asyncio
    async def test_dedup_does_not_suppress_different_thought(self, server):
        """scene_update.current_thought is preserved when it differs from chat_response."""
        ws1 = AsyncMock()
        server._window_clients = {ws1}

        await server._broadcast_to_window({
            'type': 'chat_response',
            'content': 'Hello there.',
            'expression': 'smiling',
            'timestamp': '2026-01-01T00:00:00+00:00',
        })

        await server._broadcast_to_window({
            'type': 'scene_update',
            'text': {
                'current_thought': 'A completely different thought.',
                'activity_label': 'Thinking',
            },
            'layers': {},
            'state': {},
            'timestamp': '2026-01-01T00:00:01+00:00',
        })

        scene_msg = json.loads(ws1.send.call_args_list[1][0][0])
        assert scene_msg['text']['current_thought'] == 'A completely different thought.'

    @pytest.mark.asyncio
    async def test_dedup_resets_after_one_suppression(self, server):
        """After one suppression, dedup tracker is cleared."""
        ws1 = AsyncMock()
        server._window_clients = {ws1}

        await server._broadcast_to_window({
            'type': 'chat_response',
            'content': 'First reply.',
            'expression': 'neutral',
            'timestamp': '2026-01-01T00:00:00+00:00',
        })

        # This gets suppressed
        await server._broadcast_to_window({
            'type': 'scene_update',
            'text': {'current_thought': 'First reply.', 'activity_label': 'Talking'},
            'layers': {},
            'state': {},
            'timestamp': '2026-01-01T00:00:01+00:00',
        })

        # Tracker should be reset, so next scene_update is NOT suppressed
        assert server._last_chat_response_content == ''

        await server._broadcast_to_window({
            'type': 'scene_update',
            'text': {'current_thought': 'Second thought.', 'activity_label': 'Thinking'},
            'layers': {},
            'state': {},
            'timestamp': '2026-01-01T00:00:02+00:00',
        })

        scene_msg = json.loads(ws1.send.call_args_list[2][0][0])
        assert scene_msg['text']['current_thought'] == 'Second thought.'


class TestDisconnectCleanup:
    """Test that disconnects clean up properly."""

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

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_visitor_map(self, server):
        """Explicit disconnect removes WS entry from _ws_visitor_map."""
        visitor_ws = AsyncMock()
        server._ws_visitor_map[visitor_ws] = {
            'visitor_id': 'web_alice',
            'display_name': 'Alice',
            'token': 'tok_abc',
        }

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.clock') as mock_clock, \
             patch('heartbeat_server.on_visitor_disconnect', new_callable=AsyncMock):
            mock_db.get_db = AsyncMock()
            mock_db.remove_visitor_present = AsyncMock()
            mock_db.get_engagement_state = AsyncMock(return_value=MagicMock(visitor_id=None))
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            # Simulate: DB lookup for disconnect token
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=AsyncMock(
                fetchone=AsyncMock(return_value={
                    'display_name': 'Alice',
                    'expires_at': '2026-12-31T00:00:00',
                })
            ))
            mock_db.get_db.return_value = mock_conn

            await server._handle_ws_disconnect({'token': 'tok_abc'})

            # Visitor map should be cleaned up
            assert visitor_ws not in server._ws_visitor_map

    @pytest.mark.asyncio
    async def test_broadcast_to_failed_client_removes_it(self, server):
        """Window client that errors on send is removed from set."""
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send = AsyncMock(side_effect=Exception("connection lost"))

        server._window_clients = {ws_good, ws_bad}

        await server._broadcast_to_window({
            'type': 'status',
            'status': 'awake',
            'message': 'test',
        })

        # Bad client should be removed
        assert ws_bad not in server._window_clients
        assert ws_good in server._window_clients

    @pytest.mark.asyncio
    async def test_disconnect_removes_all_sockets_for_visitor(self, server):
        """P1 regression: disconnect removes ALL sockets for a visitor_id, not just the first."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        server._ws_visitor_map[ws1] = {
            'visitor_id': 'web_alice',
            'display_name': 'Alice',
            'token': 'tok_abc',
        }
        server._ws_visitor_map[ws2] = {
            'visitor_id': 'web_alice',
            'display_name': 'Alice',
            'token': 'tok_abc',
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

            await server._handle_ws_disconnect({'token': 'tok_abc'})

            # BOTH sockets should be removed
            assert ws1 not in server._ws_visitor_map
            assert ws2 not in server._ws_visitor_map
            assert len(server._ws_visitor_map) == 0


class TestDedupRegression:
    """Regression tests for P2: dedup state leak."""

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
            return srv

    @pytest.mark.asyncio
    async def test_dedup_not_armed_when_no_clients(self, server):
        """P2 regression: chat_response with no clients doesn't arm dedup state."""
        # No clients connected
        assert len(server._window_clients) == 0

        await server._broadcast_to_window({
            'type': 'chat_response',
            'content': 'Ghost message nobody received.',
            'expression': 'neutral',
            'timestamp': '2026-01-01T00:00:00+00:00',
        })

        # Dedup should NOT be armed since nobody received the chat_response
        assert server._last_chat_response_content == ''

    @pytest.mark.asyncio
    async def test_dedup_clears_on_non_matching_scene_update(self, server):
        """P2 regression: dedup state clears after ANY scene_update, even non-matching."""
        ws1 = AsyncMock()
        server._window_clients = {ws1}

        # Send chat_response — arms dedup
        await server._broadcast_to_window({
            'type': 'chat_response',
            'content': 'Original reply.',
            'expression': 'neutral',
            'timestamp': '2026-01-01T00:00:00+00:00',
        })
        assert server._last_chat_response_content == 'Original reply.'

        # Non-matching scene_update — should clear dedup state anyway
        await server._broadcast_to_window({
            'type': 'scene_update',
            'text': {'current_thought': 'Totally different.', 'activity_label': 'Thinking'},
            'layers': {},
            'state': {},
            'timestamp': '2026-01-01T00:00:01+00:00',
        })

        # Dedup state should be cleared (not stale)
        assert server._last_chat_response_content == ''

        # A later scene_update should NOT be suppressed
        await server._broadcast_to_window({
            'type': 'scene_update',
            'text': {'current_thought': 'Original reply.', 'activity_label': 'Talking'},
            'layers': {},
            'state': {},
            'timestamp': '2026-01-01T00:00:02+00:00',
        })

        scene_msg = json.loads(ws1.send.call_args_list[2][0][0])
        assert scene_msg['text']['current_thought'] == 'Original reply.'
