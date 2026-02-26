"""Tests for TASK-058B: Chat history buffer.

Verifies:
- Messages accumulate in _chat_history
- Max cap (50) enforced
- Sleep clears history
- build_initial_state(chat_history=[...]) includes in response
- Empty history returns []
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


class TestChatHistoryBuffer:
    """Test the in-memory chat history buffer."""

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
    async def test_messages_accumulate(self, server):
        """Chat messages accumulate in _chat_history."""
        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.on_visitor_connect', new_callable=AsyncMock), \
             patch('heartbeat_server.clock') as mock_clock:
            mock_db.validate_and_consume_chat_token = AsyncMock(return_value={
                'display_name': 'Alice', 'uses_remaining': 5,
            })
            mock_db.add_visitor_present = AsyncMock()
            mock_db.update_visitor_present = AsyncMock()
            mock_db.update_visitor = AsyncMock()
            mock_db.mark_session_boundary = AsyncMock()
            mock_db.append_conversation = AsyncMock()
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            ws = AsyncMock()
            for i in range(3):
                await server._handle_ws_chat(
                    {'token': 'tok', 'text': f'Message {i}'},
                    ws,
                )

            assert len(server._chat_history) == 3
            assert server._chat_history[0]['content'] == 'Message 0'
            assert server._chat_history[2]['content'] == 'Message 2'

    @pytest.mark.asyncio
    async def test_max_cap_enforced(self, server):
        """Chat history is capped at _CHAT_HISTORY_MAX."""
        server._CHAT_HISTORY_MAX = 5

        with patch('heartbeat_server.db') as mock_db, \
             patch('heartbeat_server.on_visitor_connect', new_callable=AsyncMock), \
             patch('heartbeat_server.clock') as mock_clock:
            mock_db.validate_and_consume_chat_token = AsyncMock(return_value={
                'display_name': 'Alice', 'uses_remaining': 99,
            })
            mock_db.add_visitor_present = AsyncMock()
            mock_db.update_visitor_present = AsyncMock()
            mock_db.update_visitor = AsyncMock()
            mock_db.mark_session_boundary = AsyncMock()
            mock_db.append_conversation = AsyncMock()
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()
            mock_clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            ws = AsyncMock()
            for i in range(8):
                await server._handle_ws_chat(
                    {'token': 'tok', 'text': f'Msg {i}'},
                    ws,
                )

            assert len(server._chat_history) <= 5
            # Should keep the most recent messages
            assert server._chat_history[-1]['content'] == 'Msg 7'

    @pytest.mark.asyncio
    async def test_sleep_clears_history(self, server):
        """Entering sleep clears the chat history."""
        server._chat_history = [
            {'type': 'chat_message', 'content': 'Old msg 1'},
            {'type': 'chat_response', 'content': 'Old reply'},
        ]

        with patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._on_stage('sleep', {'status': 'entering_sleep'})

            assert len(server._chat_history) == 0

    @pytest.mark.asyncio
    async def test_dialogue_appends_to_history(self, server):
        """Shopkeeper dialogue via _on_stage is appended to history."""
        with patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._on_stage('dialogue', {
                'dialogue': 'Good evening.',
                'expression': 'smiling',
            })

            assert len(server._chat_history) == 1
            assert server._chat_history[0]['type'] == 'chat_response'
            assert server._chat_history[0]['content'] == 'Good evening.'

    @pytest.mark.asyncio
    async def test_dialogue_cap_enforced(self, server):
        """Dialogue messages also respect the history cap."""
        server._CHAT_HISTORY_MAX = 3
        server._chat_history = [
            {'type': 'chat_message', 'content': f'Msg {i}'} for i in range(3)
        ]

        with patch('heartbeat_server.clock') as mock_clock:
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            await server._on_stage('dialogue', {
                'dialogue': 'New reply.',
                'expression': 'neutral',
            })

            assert len(server._chat_history) <= 3
            assert server._chat_history[-1]['content'] == 'New reply.'


class TestBuildInitialStateWithHistory:
    """Test that build_initial_state includes chat_history."""

    @pytest.mark.asyncio
    async def test_includes_chat_history(self):
        """build_initial_state passes through chat_history list."""
        from window_state import build_initial_state

        history = [
            {'type': 'chat_message', 'sender': 'Alice', 'content': 'Hi'},
            {'type': 'chat_response', 'content': 'Welcome!'},
        ]

        from models.state import DrivesState, RoomState, EngagementState
        with patch('window_state.db') as mock_db:
            mock_db.get_drives_state = AsyncMock(return_value=DrivesState(
                social_hunger=0.5, curiosity=0.5, expression_need=0.3,
                rest_need=0.2, energy=0.8, mood_valence=0.5, mood_arousal=0.3,
            ))
            mock_db.get_room_state = AsyncMock(return_value=RoomState(
                weather='clear', shop_status='open',
            ))
            mock_db.get_engagement_state = AsyncMock(return_value=EngagementState(
                status='none',
            ))
            mock_db.get_recent_text_fragments = AsyncMock(return_value=[])
            mock_db.get_shelf_assignments = AsyncMock(return_value=[])
            mock_db.get_active_threads = AsyncMock(return_value=[])
            mock_db.get_budget_remaining = AsyncMock(return_value={'remaining': 10})
            mock_db.get_last_cycle_log = AsyncMock(return_value=None)
            mock_db.count_cycle_logs = AsyncMock(return_value=0)

            with patch('window_state.build_scene_layers', new_callable=AsyncMock) as mock_layers, \
                 patch('window_state.resolve_sprite_state', return_value='focused'), \
                 patch('window_state.resolve_time_of_day', return_value='afternoon'):
                mock_layers.return_value = MagicMock(to_dict=lambda: {'bg': 'test'})

                result = await build_initial_state(chat_history=history)

            assert 'chat_history' in result
            assert len(result['chat_history']) == 2
            assert result['chat_history'][0]['content'] == 'Hi'
            assert result['chat_history'][1]['content'] == 'Welcome!'

    @pytest.mark.asyncio
    async def test_empty_history_returns_empty_list(self):
        """build_initial_state with no chat_history returns empty list."""
        from window_state import build_initial_state

        from models.state import DrivesState, RoomState, EngagementState
        with patch('window_state.db') as mock_db:
            mock_db.get_drives_state = AsyncMock(return_value=DrivesState(
                social_hunger=0.5, curiosity=0.5, expression_need=0.3,
                rest_need=0.2, energy=0.8, mood_valence=0.5, mood_arousal=0.3,
            ))
            mock_db.get_room_state = AsyncMock(return_value=RoomState(
                weather='clear', shop_status='open',
            ))
            mock_db.get_engagement_state = AsyncMock(return_value=EngagementState(
                status='none',
            ))
            mock_db.get_recent_text_fragments = AsyncMock(return_value=[])
            mock_db.get_shelf_assignments = AsyncMock(return_value=[])
            mock_db.get_active_threads = AsyncMock(return_value=[])
            mock_db.get_budget_remaining = AsyncMock(return_value={'remaining': 10})
            mock_db.get_last_cycle_log = AsyncMock(return_value=None)
            mock_db.count_cycle_logs = AsyncMock(return_value=0)

            with patch('window_state.build_scene_layers', new_callable=AsyncMock) as mock_layers, \
                 patch('window_state.resolve_sprite_state', return_value='focused'), \
                 patch('window_state.resolve_time_of_day', return_value='afternoon'):
                mock_layers.return_value = MagicMock(to_dict=lambda: {'bg': 'test'})

                result = await build_initial_state()

            assert result['chat_history'] == []
