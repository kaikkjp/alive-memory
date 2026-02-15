"""Tests for api.dashboard_routes module (TASK-002).

Verifies that extracted dashboard route handlers produce identical
responses to the original heartbeat_server methods. Tests the handler
functions directly by mocking the server and StreamWriter.
"""

import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from api.dashboard_routes import (
    _create_dashboard_token,
    _check_dashboard_token,
    _dashboard_tokens,
    check_dashboard_auth,
    handle_auth,
    handle_vitals,
    handle_drives,
    handle_costs,
    handle_threads,
    handle_pool,
    handle_collection,
    handle_timeline,
    handle_trigger_cycle,
    handle_status,
)


def _make_server():
    """Create a mock server with _http_json and heartbeat."""
    server = MagicMock()
    server._http_json = AsyncMock()
    server.heartbeat = MagicMock()
    server.heartbeat.schedule_microcycle = AsyncMock()
    server.heartbeat._running = True
    return server


def _run(coro):
    """Run an async coroutine."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestAuthRouteHandler(unittest.TestCase):
    """Test handle_auth() endpoint handler."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    @patch.dict('os.environ', {'DASHBOARD_PASSWORD': 'secret123'})
    def test_successful_auth(self):
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'password': 'secret123'}).encode()

        _run(handle_auth(server, writer, body, '127.0.0.1'))

        server._http_json.assert_called_once()
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)
        self.assertTrue(args[0][2]['authenticated'])
        self.assertIn('token', args[0][2])

    @patch.dict('os.environ', {'DASHBOARD_PASSWORD': 'secret123'})
    def test_wrong_password(self):
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'password': 'wrong'}).encode()

        _run(handle_auth(server, writer, body, '127.0.0.1'))

        args = server._http_json.call_args
        self.assertEqual(args[0][1], 401)
        self.assertFalse(args[0][2]['authenticated'])

    @patch.dict('os.environ', {}, clear=False)
    def test_no_password_configured(self):
        # Remove DASHBOARD_PASSWORD if present
        import os
        old = os.environ.pop('DASHBOARD_PASSWORD', None)
        try:
            server = _make_server()
            writer = MagicMock()
            body = json.dumps({'password': 'anything'}).encode()

            _run(handle_auth(server, writer, body, '127.0.0.1'))

            args = server._http_json.call_args
            self.assertEqual(args[0][1], 503)
        finally:
            if old is not None:
                os.environ['DASHBOARD_PASSWORD'] = old

    def test_bad_json_body(self):
        server = _make_server()
        writer = MagicMock()

        _run(handle_auth(server, writer, b'not json', '127.0.0.1'))

        args = server._http_json.call_args
        self.assertEqual(args[0][1], 400)


class TestProtectedRoutes(unittest.TestCase):
    """Test that all dashboard data routes reject unauthenticated requests."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def _assert_unauthorized(self, handler, *extra_args):
        """Assert handler returns 401 with no auth."""
        server = _make_server()
        writer = MagicMock()
        _run(handler(server, writer, '', *extra_args))
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 401)

    def _assert_authorized(self, handler, *extra_args):
        """Assert handler proceeds (calls _http_json with 200) with valid auth."""
        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'
        _run(handler(server, writer, auth, *extra_args))
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)

    def test_vitals_unauthorized(self):
        self._assert_unauthorized(handle_vitals)

    def test_drives_unauthorized(self):
        self._assert_unauthorized(handle_drives)

    def test_costs_unauthorized(self):
        self._assert_unauthorized(handle_costs)

    def test_threads_unauthorized(self):
        self._assert_unauthorized(handle_threads)

    def test_pool_unauthorized(self):
        self._assert_unauthorized(handle_pool)

    def test_collection_unauthorized(self):
        self._assert_unauthorized(handle_collection)

    def test_timeline_unauthorized(self):
        self._assert_unauthorized(handle_timeline)

    def test_trigger_cycle_unauthorized(self):
        self._assert_unauthorized(handle_trigger_cycle)

    def test_status_unauthorized(self):
        self._assert_unauthorized(handle_status)

    @patch('api.dashboard_routes.db')
    def test_vitals_authorized(self, mock_db):
        mock_db.get_days_alive = AsyncMock(return_value=5)
        mock_db.get_visitor_count_today = AsyncMock(return_value=3)
        mock_db.get_flashbulb_count_today = AsyncMock(return_value=2)
        mock_db.get_llm_call_count_today = AsyncMock(return_value=10)
        mock_db.get_llm_call_cost_today = AsyncMock(return_value=0.42)
        self._assert_authorized(handle_vitals)

    @patch('api.dashboard_routes.db')
    def test_drives_authorized(self, mock_db):
        drives = MagicMock()
        drives.social_hunger = 0.5
        drives.curiosity = 0.6
        drives.expression_need = 0.3
        drives.rest_need = 0.2
        drives.energy = 0.8
        drives.mood_valence = 0.1
        drives.mood_arousal = 0.4
        drives.updated_at = None
        mock_db.get_drives_state = AsyncMock(return_value=drives)
        self._assert_authorized(handle_drives)

    @patch('api.dashboard_routes.db')
    def test_trigger_cycle_authorized(self, mock_db):
        self._assert_authorized(handle_trigger_cycle)

    @patch('api.dashboard_routes.db')
    def test_status_authorized(self, mock_db):
        engagement = MagicMock()
        engagement.status = 'none'
        engagement.visitor_id = None
        room = MagicMock()
        room.shop_status = 'open'
        mock_db.get_engagement_state = AsyncMock(return_value=engagement)
        mock_db.get_room_state = AsyncMock(return_value=room)
        # Mock db.get_db() → conn.execute() → cursor.fetchone()
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_db.get_db = AsyncMock(return_value=mock_conn)
        self._assert_authorized(handle_status)


class TestHeartbeatStatus(unittest.TestCase):
    """Test heartbeat status reflects actual cycle timestamps (TASK-022)."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def _get_status_response(self, mock_db, ts_str):
        """Helper: call handle_status with mocked cycle_log ts, return JSON body."""
        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'

        engagement = MagicMock()
        engagement.status = 'none'
        engagement.visitor_id = None
        room = MagicMock()
        room.shop_status = 'open'
        mock_db.get_engagement_state = AsyncMock(return_value=engagement)
        mock_db.get_room_state = AsyncMock(return_value=room)

        if ts_str is None:
            row = None
        else:
            row = {'ts': ts_str}
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=row)
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_db.get_db = AsyncMock(return_value=mock_conn)

        _run(handle_status(server, writer, auth))
        return server._http_json.call_args[0][2]

    @patch('api.dashboard_routes.db')
    def test_active_when_recent_cycle(self, mock_db):
        """Cycle within 1 expected interval → active."""
        from datetime import datetime, timezone, timedelta
        recent_ts = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        body = self._get_status_response(mock_db, recent_ts)
        self.assertEqual(body['heartbeat_status'], 'active')
        self.assertIsNotNone(body['seconds_since_last_cycle'])
        self.assertLessEqual(body['seconds_since_last_cycle'], 600)

    @patch('api.dashboard_routes.db')
    def test_late_when_stale_cycle(self, mock_db):
        """Cycle within 2 expected intervals → late."""
        from datetime import datetime, timezone, timedelta
        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=900)).isoformat()
        body = self._get_status_response(mock_db, stale_ts)
        self.assertEqual(body['heartbeat_status'], 'late')

    @patch('api.dashboard_routes.db')
    def test_inactive_when_no_recent_cycle(self, mock_db):
        """No cycle within 3 expected intervals → inactive."""
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=2000)).isoformat()
        body = self._get_status_response(mock_db, old_ts)
        self.assertEqual(body['heartbeat_status'], 'inactive')

    @patch('api.dashboard_routes.db')
    def test_inactive_when_no_cycles_exist(self, mock_db):
        """No cycle_log entries → inactive, seconds_since null."""
        body = self._get_status_response(mock_db, None)
        self.assertEqual(body['heartbeat_status'], 'inactive')
        self.assertIsNone(body['seconds_since_last_cycle'])
        self.assertIsNone(body['last_cycle_ts'])

    @patch('api.dashboard_routes.db')
    def test_response_includes_expected_interval(self, mock_db):
        """Response always includes expected_interval for frontend calculation."""
        body = self._get_status_response(mock_db, None)
        self.assertEqual(body['expected_interval'], 600)


class TestBackwardCompatImports(unittest.TestCase):
    """Verify backward-compatible imports from heartbeat_server still work."""

    def test_imports_from_heartbeat_server(self):
        from heartbeat_server import (
            _create_dashboard_token,
            _check_dashboard_token,
            _check_dashboard_auth,
            _dashboard_tokens,
            _DASHBOARD_TOKEN_TTL,
            _check_rate_limit,
            _record_auth_attempt,
            _reset_auth_attempts,
            _auth_attempts,
            _AUTH_MAX_ATTEMPTS,
            _AUTH_WINDOW_SECONDS,
        )
        # All imports should resolve without error
        assert callable(_create_dashboard_token)
        assert callable(_check_dashboard_token)
        assert callable(_check_dashboard_auth)
        assert isinstance(_dashboard_tokens, dict)

    def test_shared_token_state(self):
        """Tokens created via dashboard_routes are visible via heartbeat_server re-exports."""
        from heartbeat_server import (
            _create_dashboard_token as hs_create,
            _check_dashboard_token as hs_check,
            _dashboard_tokens as hs_tokens,
        )
        hs_tokens.clear()
        try:
            token = hs_create()
            # Should be visible from both modules
            assert hs_check(token) is True
            assert _check_dashboard_token(token) is True
        finally:
            hs_tokens.clear()


if __name__ == '__main__':
    unittest.main()
