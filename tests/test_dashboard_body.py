"""Tests for dashboard body endpoint (TASK-015, TASK-021, TASK-050).

Verifies GET /api/dashboard/body returns correct JSON shape.

TASK-050: Energy replaced with real-dollar budget. Body endpoint now returns
'budget' key (from get_budget_remaining) instead of 'energy' key.
"""

import asyncio
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db
import clock
from api.dashboard_routes import (
    _create_dashboard_token,
    _dashboard_tokens,
    handle_body,
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


class TestBodyEndpointAuth(unittest.TestCase):
    """Body endpoint rejects unauthenticated requests."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def test_body_unauthorized(self):
        server = _make_server()
        writer = MagicMock()
        _run(handle_body(server, writer, ''))
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 401)


class TestBodyEndpointData(unittest.TestCase):
    """Body endpoint returns correct JSON shape (TASK-050: budget replaces energy)."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    @patch('api.dashboard_routes.db')
    def test_body_empty_data(self, mock_db):
        """Fresh day with no actions returns empty lists and full budget."""
        mock_db.get_action_capabilities = AsyncMock(return_value=[
            {'action': 'speak', 'enabled': True, 'ready': True,
             'cooling_until': None},
        ])
        mock_db.get_budget_remaining = AsyncMock(return_value={
            'budget': 5.0, 'spent': 0.0, 'remaining': 5.0,
        })
        mock_db.get_actions_today = AsyncMock(return_value=[])

        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'

        _run(handle_body(server, writer, auth))

        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)
        body = args[0][2]

        # Verify top-level keys (TASK-050: 'budget' replaces 'energy')
        self.assertIn('capabilities', body)
        self.assertIn('budget', body)
        self.assertIn('actions_today', body)

        # Verify capabilities shape
        self.assertEqual(len(body['capabilities']), 1)
        cap = body['capabilities'][0]
        self.assertEqual(cap['action'], 'speak')
        self.assertTrue(cap['enabled'])
        self.assertTrue(cap['ready'])
        self.assertIsNone(cap['cooling_until'])

        # Verify budget shape
        self.assertEqual(body['budget']['budget'], 5.0)
        self.assertEqual(body['budget']['spent'], 0.0)
        self.assertEqual(body['budget']['remaining'], 5.0)

        # Verify empty actions today
        self.assertEqual(body['actions_today'], [])

    @patch('api.dashboard_routes.db')
    def test_body_seeded_data(self, mock_db):
        """With seeded data, returns correct budget and actions."""
        mock_db.get_action_capabilities = AsyncMock(return_value=[
            {'action': 'speak', 'enabled': True, 'ready': True,
             'cooling_until': None},
            {'action': 'browse_web', 'enabled': False, 'ready': False,
             'cooling_until': None},
        ])
        mock_db.get_budget_remaining = AsyncMock(return_value={
            'budget': 5.0, 'spent': 2.37, 'remaining': 2.63,
        })
        mock_db.get_actions_today = AsyncMock(return_value=[
            {'type': 'speak', 'count': 3, 'total_energy': 0.45},
        ])

        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'

        _run(handle_body(server, writer, auth))

        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)
        body = args[0][2]

        self.assertEqual(len(body['capabilities']), 2)
        self.assertEqual(body['budget']['spent'], 2.37)
        self.assertEqual(body['budget']['remaining'], 2.63)
        self.assertEqual(len(body['actions_today']), 1)

    @patch('api.dashboard_routes.db')
    def test_body_cooling_capability(self, mock_db):
        """Capability with active cooldown shows ready=False and cooling_until."""
        mock_db.get_action_capabilities = AsyncMock(return_value=[
            {'action': 'browse_web', 'enabled': True, 'ready': False,
             'cooling_until': '2026-02-15T12:30:00'},
        ])
        mock_db.get_budget_remaining = AsyncMock(return_value={
            'budget': 5.0, 'spent': 0.2, 'remaining': 4.8,
        })
        mock_db.get_actions_today = AsyncMock(return_value=[
            {'type': 'browse_web', 'count': 1, 'total_energy': 0.2},
        ])

        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'

        _run(handle_body(server, writer, auth))

        args = server._http_json.call_args
        body = args[0][2]
        cap = body['capabilities'][0]
        self.assertFalse(cap['ready'])
        self.assertEqual(cap['cooling_until'], '2026-02-15T12:30:00')


JST = timezone(timedelta(hours=9))


@pytest.fixture(autouse=False)
async def fresh_db(tmp_path):
    """Temp database for DB-level tests."""
    db._db = None
    original_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "test.db")
    await db.init_db()
    yield
    await db.close_db()
    db.DB_PATH = original_path


async def _seed_action(conn, action='speak', status='executed',
                       created_at_utc=None,
                       source='cortex'):
    """Insert a row into action_log with explicit UTC timestamp."""
    ts = created_at_utc or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    await conn.execute(
        """INSERT INTO action_log
           (id, cycle_id, action, status, source, impulse, created_at)
           VALUES (?, ?, ?, ?, ?, 0.8, ?)""",
        (str(uuid.uuid4()), 'cycle-1', action, status, source, ts),
    )
    await conn.commit()


class TestJSTDayBoundaries:
    """TASK-021 Fix A: dashboard queries use JST day boundaries, not UTC."""

    @pytest.mark.asyncio
    async def test_action_at_2330_jst_appears_today(self, fresh_db):
        """An action at 23:30 JST (14:30 UTC) should count as today."""
        # Fix the clock to 23:59 JST on 2026-02-15
        jst_2359 = datetime(2026, 2, 15, 23, 59, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=jst_2359)):
            conn = await db.get_db()
            # Action at 23:30 JST = 14:30 UTC on 2026-02-15
            ts_utc = datetime(2026, 2, 15, 14, 30, 0, tzinfo=timezone.utc)
            await _seed_action(conn, created_at_utc=ts_utc.strftime('%Y-%m-%d %H:%M:%S'))

            actions = await db.get_actions_today()
            assert len(actions) == 1
            assert actions[0]['type'] == 'speak'
            assert actions[0]['count'] == 1

    @pytest.mark.asyncio
    async def test_action_at_2330_jst_not_in_next_day(self, fresh_db):
        """When queried at 00:01 JST next day, the 23:30 JST action should NOT appear."""
        # Fix the clock to 00:01 JST on 2026-02-16
        jst_0001_next = datetime(2026, 2, 16, 0, 1, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=jst_0001_next)):
            conn = await db.get_db()
            # Action at 23:30 JST = 14:30 UTC on 2026-02-15 (previous JST day)
            ts_utc = datetime(2026, 2, 15, 14, 30, 0, tzinfo=timezone.utc)
            await _seed_action(conn, created_at_utc=ts_utc.strftime('%Y-%m-%d %H:%M:%S'))

            actions = await db.get_actions_today()
            assert len(actions) == 0

    @pytest.mark.asyncio
    async def test_habit_skip_count_uses_jst_boundary(self, fresh_db):
        """Habit skip count only counts within JST day boundaries."""
        jst_noon = datetime(2026, 2, 15, 12, 0, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=jst_noon)):
            conn = await db.get_db()
            # Habit action today: 09:00 JST = 00:00 UTC on Feb 15
            ts_today = datetime(2026, 2, 15, 0, 0, 0, tzinfo=timezone.utc)
            await _seed_action(conn, source='habit',
                               created_at_utc=ts_today.strftime('%Y-%m-%d %H:%M:%S'))
            # Habit action yesterday (JST): 14:00 UTC on Feb 14 = 23:00 JST Feb 14
            ts_yesterday = datetime(2026, 2, 14, 14, 0, 0, tzinfo=timezone.utc)
            await _seed_action(conn, source='habit',
                               created_at_utc=ts_yesterday.strftime('%Y-%m-%d %H:%M:%S'))

            count = await db.get_habit_skip_count_today()
            assert count == 1


class TestCooldownAccuracy:
    """TASK-021 Fix B: cooldown status is accurate (no silent TypeError)."""

    @pytest.mark.asyncio
    async def test_recently_used_action_shows_not_ready(self, fresh_db):
        """An action used 30s ago with 300s cooldown should show ready=False."""
        # browse_web has cooldown_seconds=300 in the registry
        now_jst = datetime(2026, 2, 15, 12, 0, 30, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=now_jst)):
            conn = await db.get_db()
            # Action used 30s ago (in UTC)
            used_at = (now_jst - timedelta(seconds=30)).astimezone(timezone.utc)
            await _seed_action(conn, action='browse_web',
                               created_at_utc=used_at.strftime('%Y-%m-%d %H:%M:%S'))

            caps = await db.get_action_capabilities()
            web_cap = next((c for c in caps if c['action'] == 'browse_web'), None)
            assert web_cap is not None
            # browse_web has 300s cooldown, used 30s ago: should be cooling
            assert web_cap['ready'] is False
            assert web_cap['cooling_until'] is not None

    @pytest.mark.asyncio
    async def test_old_action_shows_ready(self, fresh_db):
        """An action used long ago should show ready=True."""
        now_jst = datetime(2026, 2, 15, 12, 0, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=now_jst)):
            conn = await db.get_db()
            # Action used 2 hours ago
            used_at = (now_jst - timedelta(hours=2)).astimezone(timezone.utc)
            await _seed_action(conn, action='speak',
                               created_at_utc=used_at.strftime('%Y-%m-%d %H:%M:%S'))

            caps = await db.get_action_capabilities()
            speak_cap = next((c for c in caps if c['action'] == 'speak'), None)
            assert speak_cap is not None
            assert speak_cap['ready'] is True


if __name__ == '__main__':
    unittest.main()
