"""Tests for TASK-095 Phase 3: Public Agent API.

Verifies:
- ApiKeyManager: key loading, validation, rate limiting
- handle_chat: input validation, visitor creation, response flow
- handle_public_state: correct fields returned
- _check_api_key helper: Bearer prefix stripping
"""

import asyncio
import json
import os
import tempfile
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.api_auth import ApiKeyManager
from api import public_routes


def _run(coro):
    """Run an async coroutine."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_server():
    """Create a mock server with _http_json and heartbeat."""
    server = MagicMock()
    server._http_json = AsyncMock()
    server.heartbeat = MagicMock()
    server.heartbeat.schedule_microcycle = AsyncMock()
    server.heartbeat.wait_for_cycle_log = AsyncMock(return_value=None)
    server.heartbeat.get_health_status.return_value = {'alive': True}
    return server


# ── ApiKeyManager Tests ──


class TestApiKeyManagerInit:
    """Test key loading and initialization."""

    def test_no_path(self):
        mgr = ApiKeyManager()
        assert not mgr.has_keys

    def test_nonexistent_path(self):
        mgr = ApiKeyManager('/tmp/does-not-exist-12345.json')
        assert not mgr.has_keys

    def test_load_from_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([
                {'key': 'sk-test-1', 'name': 'App1', 'rate_limit': 30},
                {'key': 'sk-test-2', 'name': 'App2'},
            ], f)
            path = f.name
        try:
            mgr = ApiKeyManager(path)
            assert mgr.has_keys
            assert mgr.validate('sk-test-1') == {'name': 'App1', 'rate_limit': 30}
            assert mgr.validate('sk-test-2') == {'name': 'App2', 'rate_limit': 60}
        finally:
            os.unlink(path)

    def test_invalid_json_format(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({'not': 'an array'}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match='must be a JSON array'):
                ApiKeyManager(path)
        finally:
            os.unlink(path)

    def test_empty_key_skipped(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([{'key': '', 'name': 'Empty'}], f)
            path = f.name
        try:
            mgr = ApiKeyManager(path)
            assert not mgr.has_keys
        finally:
            os.unlink(path)


class TestApiKeyValidation:
    """Test key validation."""

    def test_valid_key(self):
        mgr = ApiKeyManager()
        mgr.add_key('sk-valid', name='Test', rate_limit=100)
        result = mgr.validate('sk-valid')
        assert result is not None
        assert result['name'] == 'Test'

    def test_invalid_key(self):
        mgr = ApiKeyManager()
        mgr.add_key('sk-valid', name='Test')
        assert mgr.validate('sk-wrong') is None

    def test_empty_key(self):
        mgr = ApiKeyManager()
        assert mgr.validate('') is None


class TestApiKeyRateLimit:
    """Test sliding window rate limiting."""

    def test_within_limit(self):
        mgr = ApiKeyManager()
        mgr.add_key('sk-rl', rate_limit=5)
        for _ in range(5):
            assert mgr.check_rate_limit('sk-rl') is True

    def test_exceeds_limit(self):
        mgr = ApiKeyManager()
        mgr.add_key('sk-rl', rate_limit=3)
        for _ in range(3):
            assert mgr.check_rate_limit('sk-rl') is True
        assert mgr.check_rate_limit('sk-rl') is False

    def test_unknown_key_rejected(self):
        mgr = ApiKeyManager()
        assert mgr.check_rate_limit('sk-unknown') is False

    def test_window_expiry(self):
        mgr = ApiKeyManager()
        mgr.add_key('sk-exp', rate_limit=2)

        # Fill up the limit
        assert mgr.check_rate_limit('sk-exp') is True
        assert mgr.check_rate_limit('sk-exp') is True
        assert mgr.check_rate_limit('sk-exp') is False

        # Manually expire timestamps (simulate time passing)
        old_time = time.monotonic() - 61
        mgr._rate_counters['sk-exp'] = [old_time, old_time]

        # Should be allowed again after window expires
        assert mgr.check_rate_limit('sk-exp') is True


class TestAddKey:
    """Test programmatic key addition."""

    def test_add_key(self):
        mgr = ApiKeyManager()
        assert not mgr.has_keys
        mgr.add_key('sk-new', name='New App', rate_limit=120)
        assert mgr.has_keys
        meta = mgr.validate('sk-new')
        assert meta['name'] == 'New App'
        assert meta['rate_limit'] == 120


# ── handle_chat Tests ──


class TestHandleChat:
    """Test POST /api/chat handler."""

    def test_invalid_json(self):
        server = _make_server()
        writer = MagicMock()
        _run(public_routes.handle_chat(server, writer, b'not json', {'name': 'test'}))
        args = server._http_json.call_args[0]
        assert args[1] == 400
        assert 'invalid JSON' in args[2]['error']

    def test_missing_message(self):
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'visitor_id': 'v1'}).encode()
        _run(public_routes.handle_chat(server, writer, body, {'name': 'test'}))
        args = server._http_json.call_args[0]
        assert args[1] == 400
        assert 'message field required' in args[2]['error']

    def test_empty_message(self):
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'message': '   '}).encode()
        _run(public_routes.handle_chat(server, writer, body, {'name': 'test'}))
        args = server._http_json.call_args[0]
        assert args[1] == 400

    @patch('api.public_routes.db')
    @patch('api.public_routes.on_visitor_message')
    def test_busy_returns_queued(self, mock_ack, mock_db):
        mock_db.get_visitor = AsyncMock(return_value=None)
        mock_db.upsert_visitor = AsyncMock()
        mock_db.append_conversation = AsyncMock()
        mock_db.get_engagement_state = AsyncMock(return_value=MagicMock())
        mock_ack.return_value = {'should_process': False}

        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'message': 'hello', 'visitor_id': 'v1'}).encode()
        _run(public_routes.handle_chat(server, writer, body, {'name': 'test'}))

        args = server._http_json.call_args[0]
        assert args[1] == 200
        assert args[2]['status'] == 'busy'
        assert args[2]['response'] is None

    @patch('api.public_routes.db')
    @patch('api.public_routes.on_visitor_message')
    def test_timeout_response(self, mock_ack, mock_db):
        mock_db.get_visitor = AsyncMock(return_value=MagicMock())
        mock_db.append_conversation = AsyncMock()
        mock_db.get_engagement_state = AsyncMock(return_value=MagicMock())
        mock_ack.return_value = {'should_process': True}

        server = _make_server()
        server.heartbeat.wait_for_cycle_log = AsyncMock(return_value=None)
        writer = MagicMock()
        body = json.dumps({'message': 'hello', 'visitor_id': 'v1'}).encode()
        _run(public_routes.handle_chat(server, writer, body, {'name': 'test'}))

        args = server._http_json.call_args[0]
        assert args[1] == 200
        assert args[2]['status'] == 'timeout'
        assert args[2]['response'] is None

    @patch('api.public_routes.db')
    @patch('api.public_routes.on_visitor_message')
    def test_successful_response(self, mock_ack, mock_db):
        mock_db.get_visitor = AsyncMock(return_value=MagicMock())
        mock_db.append_conversation = AsyncMock()
        mock_db.get_engagement_state = AsyncMock(return_value=MagicMock())
        mock_ack.return_value = {'should_process': True}

        server = _make_server()
        server.heartbeat.wait_for_cycle_log = AsyncMock(return_value={
            'dialogue': 'Welcome to my shop!',
            'expression': 'smile',
            'body_state': 'standing',
            'gaze': 'visitor',
        })
        writer = MagicMock()
        body = json.dumps({'message': 'hello', 'visitor_id': 'v1'}).encode()
        _run(public_routes.handle_chat(server, writer, body, {'name': 'test'}))

        args = server._http_json.call_args[0]
        assert args[1] == 200
        assert args[2]['response'] == 'Welcome to my shop!'
        assert args[2]['visitor_id'] == 'v1'
        assert 'timestamp' in args[2]
        assert args[2]['internal']['expression'] == 'smile'

    @patch('api.public_routes.db')
    @patch('api.public_routes.on_visitor_message')
    def test_auto_generated_visitor_id(self, mock_ack, mock_db):
        mock_db.get_visitor = AsyncMock(return_value=None)
        mock_db.upsert_visitor = AsyncMock()
        mock_db.append_conversation = AsyncMock()
        mock_db.get_engagement_state = AsyncMock(return_value=MagicMock())
        mock_ack.return_value = {'should_process': False}

        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'message': 'hi'}).encode()
        _run(public_routes.handle_chat(server, writer, body, {'name': 'MyApp'}))

        args = server._http_json.call_args[0]
        vid = args[2]['visitor_id']
        assert vid.startswith('api-MyApp-')
        assert len(vid) > len('api-MyApp-')

    @patch('api.public_routes.db')
    @patch('api.public_routes.on_visitor_message')
    def test_creates_new_visitor(self, mock_ack, mock_db):
        mock_db.get_visitor = AsyncMock(return_value=None)
        mock_db.upsert_visitor = AsyncMock()
        mock_db.append_conversation = AsyncMock()
        mock_db.get_engagement_state = AsyncMock(return_value=MagicMock())
        mock_ack.return_value = {'should_process': False}

        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'message': 'hello', 'visitor_id': 'new-v'}).encode()
        _run(public_routes.handle_chat(server, writer, body, {'name': 'TestApp'}))

        mock_db.upsert_visitor.assert_called_once_with('new-v', name='TestApp')


# ── handle_public_state Tests ──


class TestHandlePublicState:
    """Test GET /api/public-state handler."""

    @patch('api.public_routes.db')
    def test_state_shape(self, mock_db):
        drives = MagicMock()
        drives.mood_valence = 0.5
        drives.mood_arousal = 0.4
        drives.energy = 0.7
        engagement = MagicMock()
        engagement.status = 'none'

        mock_db.get_drives_state = AsyncMock(return_value=drives)
        mock_db.get_engagement_state = AsyncMock(return_value=engagement)

        server = _make_server()
        writer = MagicMock()
        _run(public_routes.handle_public_state(server, writer, {'name': 'test'}))

        args = server._http_json.call_args[0]
        assert args[1] == 200
        state = args[2]
        assert state['status'] == 'active'
        assert state['mood']['valence'] == 0.5
        assert state['mood']['arousal'] == 0.4
        assert state['energy'] == 0.7
        assert state['engaged'] is False
        assert 'timestamp' in state

    @patch('api.public_routes.db')
    def test_state_engaged(self, mock_db):
        drives = MagicMock()
        drives.mood_valence = 0.2
        drives.mood_arousal = 0.6
        drives.energy = 0.5
        engagement = MagicMock()
        engagement.status = 'active'

        mock_db.get_drives_state = AsyncMock(return_value=drives)
        mock_db.get_engagement_state = AsyncMock(return_value=engagement)

        server = _make_server()
        writer = MagicMock()
        _run(public_routes.handle_public_state(server, writer, {'name': 'test'}))

        args = server._http_json.call_args[0]
        assert args[2]['engaged'] is True

    @patch('api.public_routes.db')
    def test_state_inactive(self, mock_db):
        mock_db.get_drives_state = AsyncMock(return_value=MagicMock())
        mock_db.get_engagement_state = AsyncMock(return_value=MagicMock())

        server = _make_server()
        server.heartbeat.get_health_status.return_value = {'alive': False}
        writer = MagicMock()
        _run(public_routes.handle_public_state(server, writer, {'name': 'test'}))

        args = server._http_json.call_args[0]
        assert args[2]['status'] == 'inactive'

    @patch('api.public_routes.db')
    def test_state_error(self, mock_db):
        mock_db.get_drives_state = AsyncMock(side_effect=Exception('db error'))

        server = _make_server()
        writer = MagicMock()
        _run(public_routes.handle_public_state(server, writer, {'name': 'test'}))

        args = server._http_json.call_args[0]
        assert args[1] == 500


# ── _check_api_key Tests (server method) ──


class TestCheckApiKey:
    """Test the _check_api_key helper via ShopkeeperServer."""

    def _make_server_with_key(self):
        from heartbeat_server import ShopkeeperServer
        obj = object.__new__(ShopkeeperServer)
        obj._api_key_manager = ApiKeyManager()
        obj._api_key_manager.add_key('sk-test-key', name='TestApp')
        return obj

    def test_bearer_prefix(self):
        server = self._make_server_with_key()
        result = server._check_api_key('Bearer sk-test-key')
        assert result is not None
        assert result['name'] == 'TestApp'

    def test_raw_key(self):
        server = self._make_server_with_key()
        result = server._check_api_key('sk-test-key')
        assert result is not None

    def test_invalid_key(self):
        server = self._make_server_with_key()
        result = server._check_api_key('sk-wrong-key')
        assert result is None

    def test_empty_authorization(self):
        server = self._make_server_with_key()
        result = server._check_api_key('')
        assert result is None

    def test_bearer_only(self):
        server = self._make_server_with_key()
        result = server._check_api_key('Bearer ')
        assert result is None
