"""Tests for TASK-058B: Weather API endpoints.

Verifies:
- _fetch_tokyo_weather returns expected structure
- Second call within 10min returns cached (no HTTP)
- Network error returns fallback
- /api/weather route returns 200 JSON
- /api/outdoor route returns combined data
"""

import json
import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


class TestFetchTokyoWeather:
    """Test the weather data fetching and caching."""

    @pytest.fixture
    def server(self):
        from heartbeat_server import ShopkeeperServer

        with patch.object(ShopkeeperServer, '__init__', lambda self: None):
            srv = ShopkeeperServer.__new__(ShopkeeperServer)
            srv._weather_cache = {}
            srv._WEATHER_CACHE_TTL = 600
            return srv

    @pytest.mark.asyncio
    async def test_returns_expected_structure(self, server):
        """Weather data has expected fields."""
        mock_response_bytes = json.dumps({
            'current_condition': [{
                'temp_C': '15',
                'temp_F': '59',
                'humidity': '65',
                'windspeedKmph': '12',
                'FeelsLikeC': '13',
                'observation_time': '12:00 PM',
                'weatherDesc': [{'value': 'Partly cloudy'}],
            }]
        }).encode()

        # Patch urllib.request.urlopen which is called inside the lambda
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_bytes

        with patch('urllib.request.urlopen', return_value=mock_resp):
            result = await server._fetch_tokyo_weather()

        assert result['temp_c'] == 15
        assert result['condition'] == 'Partly cloudy'
        assert result['humidity'] == 65
        assert result['wind_kmph'] == 12
        assert result['location'] == 'Tokyo, Japan'

    @pytest.mark.asyncio
    async def test_cache_hit(self, server):
        """Second call within TTL returns cached data without HTTP."""
        cached_data = {
            'temp_c': 20,
            'condition': 'Clear',
            'humidity': 50,
            'wind_kmph': 8,
            'location': 'Tokyo, Japan',
        }
        server._weather_cache = {
            'data': cached_data,
            'fetched_at': time.time(),  # just now
        }

        result = await server._fetch_tokyo_weather()

        assert result == cached_data
        # No HTTP call should have been made (we didn't patch urllib)

    @pytest.mark.asyncio
    async def test_cache_expired(self, server):
        """Expired cache triggers a new fetch."""
        old_data = {'temp_c': 10, 'condition': 'Old'}
        server._weather_cache = {
            'data': old_data,
            'fetched_at': time.time() - 700,  # 11+ minutes ago
        }

        mock_response_bytes = json.dumps({
            'current_condition': [{
                'temp_C': '22',
                'temp_F': '72',
                'humidity': '45',
                'windspeedKmph': '5',
                'FeelsLikeC': '21',
                'observation_time': '3:00 PM',
                'weatherDesc': [{'value': 'Sunny'}],
            }]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_bytes

        with patch('urllib.request.urlopen', return_value=mock_resp):
            result = await server._fetch_tokyo_weather()

        assert result['temp_c'] == 22
        assert result['condition'] == 'Sunny'

    @pytest.mark.asyncio
    async def test_network_error_returns_cached_fallback(self, server):
        """Network error returns last cached data as fallback."""
        cached_data = {'temp_c': 18, 'condition': 'Cached', 'location': 'Tokyo, Japan'}
        server._weather_cache = {
            'data': cached_data,
            'fetched_at': time.time() - 700,  # expired
        }

        with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
            result = await server._fetch_tokyo_weather()

        assert result == cached_data

    @pytest.mark.asyncio
    async def test_network_error_no_cache_returns_error(self, server):
        """Network error with no cache returns error dict."""
        server._weather_cache = {}

        with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
            result = await server._fetch_tokyo_weather()

        assert 'error' in result
        assert result['location'] == 'Tokyo, Japan'


class TestWeatherHttpHandlers:
    """Test the HTTP handler methods for weather endpoints."""

    @pytest.fixture
    def server(self):
        from heartbeat_server import ShopkeeperServer

        with patch.object(ShopkeeperServer, '__init__', lambda self: None):
            srv = ShopkeeperServer.__new__(ShopkeeperServer)
            srv._weather_cache = {}
            srv._WEATHER_CACHE_TTL = 600
            return srv

    @pytest.mark.asyncio
    async def test_http_weather_returns_json(self, server):
        """_http_weather calls _fetch and writes JSON response."""
        writer = AsyncMock()

        weather_data = {
            'temp_c': 15,
            'condition': 'Cloudy',
            'humidity': 70,
            'wind_kmph': 10,
            'location': 'Tokyo, Japan',
        }

        # Pre-fill cache so _fetch_tokyo_weather returns immediately
        server._weather_cache = {
            'data': weather_data,
            'fetched_at': time.time(),
        }
        server._http_json = AsyncMock()

        await server._http_weather(writer)

        server._http_json.assert_called_once_with(writer, 200, weather_data)

    @pytest.mark.asyncio
    async def test_http_outdoor_returns_combined(self, server):
        """_http_outdoor combines weather + room state."""
        writer = AsyncMock()

        weather_data = {'temp_c': 20, 'condition': 'Clear'}
        room_state = MagicMock(
            weather='clear',
            time_of_day='afternoon',
            shop_status='open',
        )

        # Pre-fill cache so _fetch_tokyo_weather returns immediately
        server._weather_cache = {
            'data': weather_data,
            'fetched_at': time.time(),
        }
        server._http_json = AsyncMock()

        with patch('heartbeat_server.db') as mock_db:
            mock_db.get_room_state = AsyncMock(return_value=room_state)

            await server._http_outdoor(writer)

            server._http_json.assert_called_once()
            call_args = server._http_json.call_args
            status_code = call_args[0][1]
            body = call_args[0][2]

            assert status_code == 200
            assert body['weather'] == weather_data
            assert body['shop_weather'] == 'clear'
            assert body['time_of_day'] == 'afternoon'
            assert body['shop_status'] == 'open'


class TestHttpStateEndpoint:
    """P3 regression: /api/state must include chat_history."""

    @pytest.fixture
    def server(self):
        from heartbeat_server import ShopkeeperServer

        with patch.object(ShopkeeperServer, '__init__', lambda self: None):
            srv = ShopkeeperServer.__new__(ShopkeeperServer)
            srv._weather_cache = {}
            srv._WEATHER_CACHE_TTL = 600
            srv._chat_history = [
                {'type': 'chat_message', 'sender': 'Alice', 'content': 'Hi'},
                {'type': 'chat_response', 'content': 'Welcome!'},
            ]
            return srv

    @pytest.mark.asyncio
    async def test_http_state_includes_chat_history(self, server):
        """GET /api/state response includes chat_history matching WS initial payload."""
        writer = AsyncMock()
        server._http_json = AsyncMock()

        with patch('window_state.build_initial_state', new_callable=AsyncMock) as mock_build:
            mock_build.return_value = {
                'type': 'initial_state',
                'chat_history': server._chat_history,
            }

            await server._http_state(writer)

            # build_initial_state should be called with chat_history
            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]
            assert 'chat_history' in call_kwargs
            assert len(call_kwargs['chat_history']) == 2
            assert call_kwargs['chat_history'][0]['content'] == 'Hi'


class TestWeatherBuilderHelpers:
    """Test window_state builder helper functions."""

    def test_build_chat_message(self):
        """build_chat_message returns properly structured dict."""
        from window_state import build_chat_message

        msg = build_chat_message(
            sender='Alice',
            sender_type='visitor',
            content='Hello!',
            timestamp='2026-01-01T00:00:00+00:00',
        )

        assert msg['type'] == 'chat_message'
        assert msg['sender'] == 'Alice'
        assert msg['sender_type'] == 'visitor'
        assert msg['content'] == 'Hello!'
        assert msg['timestamp'] == '2026-01-01T00:00:00+00:00'

    def test_build_chat_message_auto_timestamp(self):
        """build_chat_message generates timestamp when not provided."""
        from window_state import build_chat_message

        msg = build_chat_message('Bob', 'visitor', 'Hi')
        assert 'timestamp' in msg
        assert msg['timestamp']  # non-empty

    def test_build_visitor_presence_message(self):
        """build_visitor_presence_message returns properly structured dict."""
        from window_state import build_visitor_presence_message

        visitors = [
            {'display_name': 'Alice', 'visitor_id': 'web_alice'},
            {'display_name': 'Bob', 'visitor_id': 'web_bob'},
        ]
        msg = build_visitor_presence_message(
            visitors=visitors,
            timestamp='2026-01-01T00:00:00+00:00',
        )

        assert msg['type'] == 'visitor_presence'
        assert msg['visitor_count'] == 2
        assert len(msg['visitors']) == 2
        assert msg['visitors'][0]['display_name'] == 'Alice'

    def test_build_visitor_presence_empty(self):
        """Empty visitors list produces count=0."""
        from window_state import build_visitor_presence_message

        msg = build_visitor_presence_message(visitors=[])
        assert msg['visitor_count'] == 0
        assert msg['visitors'] == []
