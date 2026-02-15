"""Tests for dashboard behavioral endpoint (TASK-015).

Verifies GET /api/dashboard/behavioral returns correct JSON shape
with both empty and seeded data. Verifies suppressions filter by min_impulse.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from api.dashboard_routes import (
    _create_dashboard_token,
    _dashboard_tokens,
    handle_behavioral,
)


def _make_server():
    server = MagicMock()
    server._http_json = AsyncMock()
    return server


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestBehavioralEndpointAuth(unittest.TestCase):
    """Behavioral endpoint rejects unauthenticated requests."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def test_behavioral_unauthorized(self):
        server = _make_server()
        writer = MagicMock()
        _run(handle_behavioral(server, writer, ''))
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 401)


class TestBehavioralEndpointData(unittest.TestCase):
    """Behavioral endpoint returns correct JSON shape."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    @patch('api.dashboard_routes.db')
    def test_behavioral_empty_data(self, mock_db):
        """No habits, inhibitions, or suppressions returns empty lists."""
        mock_db.get_top_habits = AsyncMock(return_value=[])
        mock_db.get_active_inhibitions = AsyncMock(return_value=[])
        mock_db.get_recent_suppressions_dashboard = AsyncMock(return_value=[])
        mock_db.get_habit_skip_count_today = AsyncMock(return_value=0)

        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'

        _run(handle_behavioral(server, writer, auth))

        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)
        body = args[0][2]

        self.assertIn('habits', body)
        self.assertIn('inhibitions', body)
        self.assertIn('suppressions', body)
        self.assertIn('habit_skips_today', body)

        self.assertEqual(body['habits'], [])
        self.assertEqual(body['inhibitions'], [])
        self.assertEqual(body['suppressions'], [])
        self.assertEqual(body['habit_skips_today'], 0)

    @patch('api.dashboard_routes.db')
    def test_behavioral_seeded_data(self, mock_db):
        """With seeded data, returns correct structures."""
        mock_db.get_top_habits = AsyncMock(return_value=[
            {'action': 'write_journal', 'trigger_context': 'mid:neutral:idle:afternoon:false',
             'strength': 0.72, 'last_fired': '2026-02-15T10:00:00',
             'fire_count': 8},
        ])
        mock_db.get_active_inhibitions = AsyncMock(return_value=[
            {'action': 'speak', 'context': '{"mood_band":"negative"}',
             'strength': 0.35, 'trigger_count': 3, 'formed_at': '2026-02-14'},
        ])
        mock_db.get_recent_suppressions_dashboard = AsyncMock(return_value=[
            {'action': 'rearrange', 'impulse': 0.7,
             'reason': 'energy_gating', 'timestamp': '2026-02-15T11:00:00'},
        ])
        mock_db.get_habit_skip_count_today = AsyncMock(return_value=4)

        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'

        _run(handle_behavioral(server, writer, auth))

        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)
        body = args[0][2]

        # Habits
        self.assertEqual(len(body['habits']), 1)
        habit = body['habits'][0]
        self.assertEqual(habit['action'], 'write_journal')
        self.assertEqual(habit['strength'], 0.72)
        self.assertEqual(habit['fire_count'], 8)

        # Inhibitions
        self.assertEqual(len(body['inhibitions']), 1)
        inh = body['inhibitions'][0]
        self.assertEqual(inh['action'], 'speak')
        self.assertEqual(inh['strength'], 0.35)
        self.assertEqual(inh['trigger_count'], 3)

        # Suppressions
        self.assertEqual(len(body['suppressions']), 1)
        sup = body['suppressions'][0]
        self.assertEqual(sup['action'], 'rearrange')
        self.assertEqual(sup['impulse'], 0.7)
        self.assertEqual(sup['reason'], 'energy_gating')

        # Habit skips
        self.assertEqual(body['habit_skips_today'], 4)

    @patch('api.dashboard_routes.db')
    def test_suppressions_filter_min_impulse(self, mock_db):
        """Verify suppressions are called with min_impulse=0.5."""
        mock_db.get_top_habits = AsyncMock(return_value=[])
        mock_db.get_active_inhibitions = AsyncMock(return_value=[])
        mock_db.get_recent_suppressions_dashboard = AsyncMock(return_value=[])
        mock_db.get_habit_skip_count_today = AsyncMock(return_value=0)

        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'

        _run(handle_behavioral(server, writer, auth))

        # Verify the correct min_impulse parameter was passed
        mock_db.get_recent_suppressions_dashboard.assert_called_once_with(
            limit=10, min_impulse=0.5
        )


if __name__ == '__main__':
    unittest.main()
