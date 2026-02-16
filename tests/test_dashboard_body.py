"""Tests for dashboard body endpoint (TASK-015, TASK-021).

Verifies GET /api/dashboard/body returns correct JSON shape
with both empty and seeded action_log data.

TASK-021 additions:
- JST day boundary tests: action at 23:30 JST appears in today, not after midnight.
- Cooldown accuracy: recently-used action returns ready=False (no TypeError swallow).
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
    """Body endpoint returns correct JSON shape."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    @patch('api.dashboard_routes.db')
    def test_body_empty_data(self, mock_db):
        """Fresh day with no actions returns empty lists and zero energy."""
        mock_db.get_action_capabilities = AsyncMock(return_value=[
            {'action': 'speak', 'enabled': True, 'ready': True,
             'cooling_until': None, 'energy_cost': 0.15},
        ])
        mock_db.get_energy_budget = AsyncMock(return_value={
            'spent_today': 0, 'budget': 1.0,
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

        # Verify top-level keys
        self.assertIn('capabilities', body)
        self.assertIn('energy', body)
        self.assertIn('actions_today', body)

        # Verify capabilities shape
        self.assertEqual(len(body['capabilities']), 1)
        cap = body['capabilities'][0]
        self.assertEqual(cap['action'], 'speak')
        self.assertTrue(cap['enabled'])
        self.assertTrue(cap['ready'])
        self.assertIsNone(cap['cooling_until'])
        self.assertEqual(cap['energy_cost'], 0.15)

        # Verify energy shape
        self.assertEqual(body['energy']['spent_today'], 0)
        self.assertEqual(body['energy']['budget'], 1.0)

        # Verify empty actions today
        self.assertEqual(body['actions_today'], [])

    @patch('api.dashboard_routes.db')
    def test_body_seeded_data(self, mock_db):
        """With seeded action_log entries, returns correct counts."""
        mock_db.get_action_capabilities = AsyncMock(return_value=[
            {'action': 'speak', 'enabled': True, 'ready': True,
             'cooling_until': None, 'energy_cost': 0.15},
            {'action': 'browse_web', 'enabled': False, 'ready': False,
             'cooling_until': None, 'energy_cost': 0.2},
        ])
        mock_db.get_energy_budget = AsyncMock(return_value={
            'spent_today': 0.45, 'budget': 1.0,
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
        self.assertEqual(body['energy']['spent_today'], 0.45)
        self.assertEqual(len(body['actions_today']), 1)
        self.assertEqual(body['actions_today'][0]['type'], 'speak')
        self.assertEqual(body['actions_today'][0]['count'], 3)

    @patch('api.dashboard_routes.db')
    def test_body_cooling_capability(self, mock_db):
        """Capability with active cooldown shows ready=False and cooling_until."""
        mock_db.get_action_capabilities = AsyncMock(return_value=[
            {'action': 'browse_web', 'enabled': True, 'ready': False,
             'cooling_until': '2026-02-15T12:30:00', 'energy_cost': 0.2},
        ])
        mock_db.get_energy_budget = AsyncMock(return_value={
            'spent_today': 0.2, 'budget': 1.0,
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
                       created_at_utc=None, energy_cost=0.15,
                       source='cortex'):
    """Insert a row into action_log with explicit UTC timestamp."""
    ts = created_at_utc or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    await conn.execute(
        """INSERT INTO action_log
           (id, cycle_id, action, status, source, impulse, energy_cost, created_at)
           VALUES (?, ?, ?, ?, ?, 0.8, ?, ?)""",
        (str(uuid.uuid4()), 'cycle-1', action, status, source, energy_cost, ts),
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
    async def test_energy_budget_uses_jst_boundary(self, fresh_db):
        """Energy budget sums only actions within JST day boundaries."""
        jst_2359 = datetime(2026, 2, 15, 23, 59, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=jst_2359)):
            conn = await db.get_db()
            # Action within today (JST): 10:00 JST = 01:00 UTC
            ts_today = datetime(2026, 2, 15, 1, 0, 0, tzinfo=timezone.utc)
            await _seed_action(conn, created_at_utc=ts_today.strftime('%Y-%m-%d %H:%M:%S'),
                               energy_cost=0.2)
            # Action from yesterday (JST): 23:00 JST on Feb 14 = 14:00 UTC on Feb 14
            ts_yesterday = datetime(2026, 2, 14, 14, 0, 0, tzinfo=timezone.utc)
            await _seed_action(conn, created_at_utc=ts_yesterday.strftime('%Y-%m-%d %H:%M:%S'),
                               energy_cost=0.3)

            budget = await db.get_energy_budget()
            assert budget['spent_today'] == 0.2

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


async def _seed_cycle(conn, ts_utc_str, token_budget=3000, mode='idle'):
    """Insert a row into cycle_log with explicit UTC timestamp."""
    await conn.execute(
        """INSERT INTO cycle_log
           (id, mode, token_budget, ts)
           VALUES (?, ?, ?, ?)""",
        (str(uuid.uuid4()), mode, token_budget, ts_utc_str),
    )
    await conn.commit()


class TestEnergyBudgetCycleLog:
    """Verify get_energy_budget counts cortex cycles from cycle_log."""

    @pytest.mark.asyncio
    async def test_cycle_log_based_energy(self, fresh_db):
        """Cortex cycles in cycle_log contribute 0.03 energy each."""
        jst_noon = datetime(2026, 2, 15, 12, 0, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=jst_noon)):
            conn = await db.get_db()
            # Seed 10 cortex cycles today (token_budget > 0)
            for i in range(10):
                ts = datetime(2026, 2, 15, 1 + i, 0, 0, tzinfo=timezone.utc)
                await _seed_cycle(conn, ts.strftime('%Y-%m-%d %H:%M:%S'),
                                  token_budget=3000)
            budget = await db.get_energy_budget()
            assert budget['spent_today'] == pytest.approx(0.3, abs=0.001)
            assert budget['budget'] == 4.0

    @pytest.mark.asyncio
    async def test_rest_cycles_excluded(self, fresh_db):
        """Cycles with token_budget=0 (rest/habit) don't count toward energy."""
        jst_noon = datetime(2026, 2, 15, 12, 0, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=jst_noon)):
            conn = await db.get_db()
            # 5 cortex cycles + 3 rest cycles (token_budget=0)
            for i in range(5):
                ts = datetime(2026, 2, 15, 1 + i, 0, 0, tzinfo=timezone.utc)
                await _seed_cycle(conn, ts.strftime('%Y-%m-%d %H:%M:%S'),
                                  token_budget=3000)
            for i in range(3):
                ts = datetime(2026, 2, 15, 6 + i, 0, 0, tzinfo=timezone.utc)
                await _seed_cycle(conn, ts.strftime('%Y-%m-%d %H:%M:%S'),
                                  token_budget=0, mode='rest')
            budget = await db.get_energy_budget()
            # Only 5 cortex cycles count: 5 * 0.03 = 0.15
            assert budget['spent_today'] == pytest.approx(0.15, abs=0.001)

    @pytest.mark.asyncio
    async def test_cycle_plus_action_energy_combined(self, fresh_db):
        """Energy from cycle_log and action_log are summed together."""
        jst_noon = datetime(2026, 2, 15, 12, 0, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=jst_noon)):
            conn = await db.get_db()
            # 10 cortex cycles = 0.30
            for i in range(10):
                ts = datetime(2026, 2, 15, 1 + i, 0, 0, tzinfo=timezone.utc)
                await _seed_cycle(conn, ts.strftime('%Y-%m-%d %H:%M:%S'),
                                  token_budget=3000)
            # 1 action with 0.15 energy
            ts_action = datetime(2026, 2, 15, 2, 0, 0, tzinfo=timezone.utc)
            await _seed_action(conn, energy_cost=0.15,
                               created_at_utc=ts_action.strftime('%Y-%m-%d %H:%M:%S'))
            budget = await db.get_energy_budget()
            # 0.30 (cycles) + 0.15 (action) = 0.45
            assert budget['spent_today'] == pytest.approx(0.45, abs=0.001)

    @pytest.mark.asyncio
    async def test_yesterday_cycles_excluded(self, fresh_db):
        """Cycles from previous JST day don't count."""
        jst_noon = datetime(2026, 2, 15, 12, 0, 0, tzinfo=JST)
        with patch.object(clock, '_clock', clock.Clock(simulate=True, start=jst_noon)):
            conn = await db.get_db()
            # Yesterday's cycle (in UTC: 14:00 Feb 14 = 23:00 JST Feb 14)
            ts_yesterday = datetime(2026, 2, 14, 14, 0, 0, tzinfo=timezone.utc)
            await _seed_cycle(conn, ts_yesterday.strftime('%Y-%m-%d %H:%M:%S'),
                              token_budget=3000)
            # Today's cycle
            ts_today = datetime(2026, 2, 15, 1, 0, 0, tzinfo=timezone.utc)
            await _seed_cycle(conn, ts_today.strftime('%Y-%m-%d %H:%M:%S'),
                              token_budget=3000)
            budget = await db.get_energy_budget()
            # Only today's cycle counts: 1 * 0.03 = 0.03
            assert budget['spent_today'] == pytest.approx(0.03, abs=0.001)


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
