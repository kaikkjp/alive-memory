"""Tests for TASK-037: Dashboard cycle interval control.

Covers:
- POST changes interval, GET reflects new value
- Rejects below 10s and above 600s
- Returns 401 without auth
- Heartbeat._get_cycle_interval respects the setting
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from api.dashboard_routes import (
    _create_dashboard_token,
    _dashboard_tokens,
    handle_get_cycle_interval,
    handle_set_cycle_interval,
)
from heartbeat import Heartbeat


def _make_server():
    """Create a mock server with _http_json and a real Heartbeat."""
    server = MagicMock()
    server._http_json = AsyncMock()
    server.heartbeat = Heartbeat()
    return server


def _auth_header():
    """Create a valid auth header."""
    token = _create_dashboard_token()
    return f'Bearer {token}'


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestCycleIntervalAPI(unittest.TestCase):
    """Test cycle interval GET and POST endpoints."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def test_get_returns_current_interval(self):
        """GET returns current interval with min/max bounds."""
        server = _make_server()
        writer = MagicMock()
        auth = _auth_header()

        _run(handle_get_cycle_interval(server, writer, auth))

        server._http_json.assert_called_once()
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        data = args[2]
        self.assertIn('interval_seconds', data)
        self.assertIn('min', data)
        self.assertIn('max', data)
        self.assertEqual(data['interval_seconds'], Heartbeat.INTERVAL_DEFAULT)
        self.assertEqual(data['min'], Heartbeat.INTERVAL_MIN)
        self.assertEqual(data['max'], Heartbeat.INTERVAL_MAX)

    def test_post_changes_interval(self):
        """POST changes interval, GET reflects new value."""
        server = _make_server()
        writer = MagicMock()
        auth = _auth_header()

        body = json.dumps({'interval_seconds': 30}).encode()
        _run(handle_set_cycle_interval(server, writer, auth, body))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        self.assertEqual(args[2]['interval_seconds'], 30)

        # Verify heartbeat internal state updated
        self.assertEqual(server.heartbeat.get_cycle_interval(), 30)

        # GET should now reflect the new value
        server._http_json.reset_mock()
        _run(handle_get_cycle_interval(server, writer, auth))
        args = server._http_json.call_args[0]
        self.assertEqual(args[2]['interval_seconds'], 30)

    def test_rejects_below_min(self):
        """POST rejects interval below INTERVAL_MIN (10s)."""
        server = _make_server()
        writer = MagicMock()
        auth = _auth_header()

        body = json.dumps({'interval_seconds': 5}).encode()
        _run(handle_set_cycle_interval(server, writer, auth, body))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 400)
        self.assertIn('error', args[2])

    def test_rejects_above_max(self):
        """POST rejects interval above INTERVAL_MAX (600s)."""
        server = _make_server()
        writer = MagicMock()
        auth = _auth_header()

        body = json.dumps({'interval_seconds': 999}).encode()
        _run(handle_set_cycle_interval(server, writer, auth, body))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 400)
        self.assertIn('error', args[2])

    def test_rejects_non_numeric(self):
        """POST rejects non-numeric interval_seconds."""
        server = _make_server()
        writer = MagicMock()
        auth = _auth_header()

        body = json.dumps({'interval_seconds': 'fast'}).encode()
        _run(handle_set_cycle_interval(server, writer, auth, body))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 400)

    def test_rejects_bad_json(self):
        """POST rejects malformed JSON."""
        server = _make_server()
        writer = MagicMock()
        auth = _auth_header()

        _run(handle_set_cycle_interval(server, writer, auth, b'not json'))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 400)

    def test_get_unauthorized(self):
        """GET returns 401 without auth."""
        server = _make_server()
        writer = MagicMock()

        _run(handle_get_cycle_interval(server, writer, ''))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 401)

    def test_post_unauthorized(self):
        """POST returns 401 without auth."""
        server = _make_server()
        writer = MagicMock()

        body = json.dumps({'interval_seconds': 30}).encode()
        _run(handle_set_cycle_interval(server, writer, '', body))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 401)


class TestHeartbeatInterval(unittest.TestCase):
    """Test Heartbeat interval methods directly."""

    def test_default_interval(self):
        hb = Heartbeat()
        self.assertEqual(hb.get_cycle_interval(), Heartbeat.INTERVAL_DEFAULT)

    def test_set_interval(self):
        hb = Heartbeat()
        actual = hb.set_cycle_interval(30)
        self.assertEqual(actual, 30)
        self.assertEqual(hb.get_cycle_interval(), 30)

    def test_set_interval_clamps_low(self):
        hb = Heartbeat()
        actual = hb.set_cycle_interval(1)
        self.assertEqual(actual, Heartbeat.INTERVAL_MIN)

    def test_set_interval_clamps_high(self):
        hb = Heartbeat()
        actual = hb.set_cycle_interval(9999)
        self.assertEqual(actual, Heartbeat.INTERVAL_MAX)

    def test_get_cycle_interval_idle(self):
        """_get_cycle_interval('idle') returns value near the set interval."""
        hb = Heartbeat()
        hb.set_cycle_interval(100)
        # Run many times, check within jitter range (75-125% of 100)
        results = [hb._get_cycle_interval('idle') for _ in range(100)]
        self.assertTrue(all(r >= 75 for r in results))
        self.assertTrue(all(r <= 125 for r in results))

    def test_get_cycle_interval_rest_is_longer(self):
        """_get_cycle_interval('rest') uses 2.5x multiplier."""
        hb = Heartbeat()
        hb.set_cycle_interval(100)
        # Rest: 2.5x = 250 base, jitter 75-125% = 187-312
        results = [hb._get_cycle_interval('rest') for _ in range(100)]
        self.assertTrue(all(r >= 187 for r in results))
        self.assertTrue(all(r <= 312 for r in results))

    def test_get_cycle_interval_focused(self):
        """_get_cycle_interval('focused') same range as idle."""
        hb = Heartbeat()
        hb.set_cycle_interval(60)
        results = [hb._get_cycle_interval('focused') for _ in range(100)]
        self.assertTrue(all(r >= 45 for r in results))
        self.assertTrue(all(r <= 75 for r in results))


if __name__ == '__main__':
    unittest.main()
