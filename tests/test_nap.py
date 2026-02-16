"""Tests for TASK-038: Replace rest mode with nap consolidation."""

import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

import sleep
import clock
from heartbeat import Heartbeat
from models.event import Event


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _moment(id="m1", salience=0.8, moment_type="conversation",
            visitor_id="v1", tags=None, retry_count=0):
    return types.SimpleNamespace(
        id=id,
        retry_count=retry_count,
        visitor_id=visitor_id,
        summary=f"summary for {id}",
        moment_type=moment_type,
        tags=tags or ["music"],
        ts=datetime(2026, 2, 10, tzinfo=timezone.utc),
        salience=salience,
    )


# ─── Nap Consolidation Tests (sleep.py) ───


class TestNapConsolidate(unittest.IsolatedAsyncioTestCase):
    """Test nap_consolidate() in sleep.py."""

    async def test_nap_processes_top_moments(self):
        """nap_consolidate processes top 3 moments by salience."""
        moments = [
            _moment(id="m1", salience=0.9),
            _moment(id="m2", salience=0.8),
            _moment(id="m3", salience=0.7),
        ]

        insert_journal_mock = AsyncMock(return_value="j1")
        mark_nap_mock = AsyncMock()

        patches = [
            patch.object(sleep.db, "get_top_unprocessed_moments",
                         new=AsyncMock(return_value=moments)),
            patch.object(sleep, "gather_hot_context",
                         new=AsyncMock(return_value={})),
            patch.object(sleep, "sleep_reflect", new=AsyncMock(return_value={
                "memory_updates": [], "reflection": "nap reflection"
            })),
            patch.object(sleep.db, "mark_day_memory_processed",
                         new=AsyncMock()),
            patch.object(sleep.db, "mark_moments_nap_processed",
                         new=mark_nap_mock),
            patch.object(sleep.db, "increment_day_memory_retry",
                         new=AsyncMock()),
            patch.object(sleep.db, "insert_journal",
                         new=insert_journal_mock),
            patch.object(sleep, "hippocampus_consolidate",
                         new=AsyncMock()),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await sleep.nap_consolidate(top_n=3)

        self.assertEqual(result, 3)
        self.assertEqual(insert_journal_mock.await_count, 3)
        # Journal entries tagged with 'nap_reflection'
        for c in insert_journal_mock.await_args_list:
            tags = c.kwargs.get('tags', [])
            self.assertIn('nap_reflection', tags)

        # All 3 moment IDs marked as nap_processed
        mark_nap_mock.assert_awaited_once()
        marked_ids = mark_nap_mock.await_args[0][0]
        self.assertEqual(set(marked_ids), {"m1", "m2", "m3"})

    async def test_nap_no_moments(self):
        """nap_consolidate returns 0 when no unprocessed moments."""
        with patch.object(sleep.db, "get_top_unprocessed_moments",
                          new=AsyncMock(return_value=[])):
            result = await sleep.nap_consolidate()
        self.assertEqual(result, 0)

    async def test_nap_skips_poison_moments(self):
        """Moments at max retry count are skipped."""
        moments = [
            _moment(id="m1", retry_count=3),
        ]
        mark_nap_mock = AsyncMock()

        patches = [
            patch.object(sleep.db, "get_top_unprocessed_moments",
                         new=AsyncMock(return_value=moments)),
            patch.object(sleep.db, "mark_day_memory_processed",
                         new=AsyncMock()),
            patch.object(sleep.db, "mark_moments_nap_processed",
                         new=mark_nap_mock),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await sleep.nap_consolidate()
        self.assertEqual(result, 1)  # counted as handled
        mark_nap_mock.assert_awaited_once()

    async def test_nap_handles_reflection_failure(self):
        """If reflection fails, moment gets retry incremented."""
        moments = [_moment(id="m1")]
        retry_mock = AsyncMock()
        mark_nap_mock = AsyncMock()

        patches = [
            patch.object(sleep.db, "get_top_unprocessed_moments",
                         new=AsyncMock(return_value=moments)),
            patch.object(sleep, "gather_hot_context",
                         new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(sleep.db, "increment_day_memory_retry",
                         new=retry_mock),
            patch.object(sleep.db, "mark_moments_nap_processed",
                         new=mark_nap_mock),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await sleep.nap_consolidate()
        self.assertEqual(result, 0)
        retry_mock.assert_awaited_once_with("m1")


# ─── Night Sleep Exclusion Tests ───


class TestNapMomentsExcludedFromNightSleep(unittest.IsolatedAsyncioTestCase):
    """Test that nap_processed moments are excluded from night sleep."""

    async def test_night_sleep_skips_nap_processed(self):
        """get_unprocessed_day_memory should exclude nap_processed moments."""
        # This is a unit test of the SQL query logic
        # We verify that the function call includes the nap_processed filter
        # by checking the mock is called with the right parameters
        from db.memory import get_unprocessed_day_memory
        from unittest.mock import AsyncMock

        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        with patch("db.memory._connection.get_db",
                    new=AsyncMock(return_value=mock_conn)):
            result = await get_unprocessed_day_memory(min_salience=0.65, limit=7)

        self.assertEqual(result, [])
        # Verify the SQL includes nap_processed filter
        sql_call = mock_conn.execute.await_args[0][0]
        self.assertIn("nap_processed", sql_call)
        self.assertIn("COALESCE", sql_call)


# ─── Heartbeat Nap Trigger Tests ───


class TestHeartbeatNapTrigger(unittest.IsolatedAsyncioTestCase):
    """Test nap triggering logic in heartbeat.run_cycle."""

    def _make_heartbeat(self):
        hb = Heartbeat()
        hb.running = True
        hb._arbiter_state = {
            'consume_count_today': 0, 'news_engage_count_today': 0,
            'thread_focus_count_today': 0, 'express_count_today': 0,
            'last_consume_ts': None, 'last_news_engage_ts': None,
            'last_thread_focus_ts': None, 'last_express_ts': None,
            'recent_focus_keywords': [], 'current_date_jst': '',
        }
        return hb

    async def test_nap_triggers_on_budget_exceeded(self):
        """Budget exceeded + cooldown elapsed -> nap runs."""
        hb = self._make_heartbeat()
        hb._last_nap_ts = None  # no previous nap

        # Mock all dependencies
        mock_drives = types.SimpleNamespace(
            social_hunger=0.5, curiosity=0.5, expression_need=0.3,
            rest_need=0.4, energy=0.3, mood_valence=0.0, mood_arousal=0.5,
            copy=lambda self: types.SimpleNamespace(**self.__dict__),
        )
        mock_drives.copy = lambda: types.SimpleNamespace(**mock_drives.__dict__)

        mock_engagement = types.SimpleNamespace(
            status='none', visitor_id=None, turn_count=0,
            last_activity=None,
        )
        mock_routing = types.SimpleNamespace(
            cycle_type='idle', token_budget=3000, focus=None,
            memory_requests=[],
        )
        mock_perception = types.SimpleNamespace(
            salience=0.3, p_type='ambient', source='ambient',
            features={}, content='quiet',
        )

        nap_mock = AsyncMock(return_value=2)
        append_event_mock = AsyncMock()

        patches = [
            patch("heartbeat.db.inbox_get_unread",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.db.get_drives_state",
                  new=AsyncMock(return_value=mock_drives)),
            patch("heartbeat.update_drives",
                  new=AsyncMock(return_value=(mock_drives, []))),
            patch("heartbeat.build_perceptions",
                  new=AsyncMock(return_value=[mock_perception])),
            patch("heartbeat.perception_gate",
                  return_value=[mock_perception]),
            patch("heartbeat.apply_affect_lens",
                  return_value=[mock_perception]),
            patch("heartbeat.db.get_engagement_state",
                  new=AsyncMock(return_value=mock_engagement)),
            patch("heartbeat.route",
                  new=AsyncMock(return_value=mock_routing)),
            patch("heartbeat.recall",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.check_habits",
                  new=AsyncMock(return_value=None)),
            patch("heartbeat.db.get_energy_budget",
                  new=AsyncMock(return_value={'spent_today': 4.5, 'budget': 4.0})),
            patch("heartbeat.nap_consolidate", new=nap_mock),
            patch("heartbeat.db.append_event", new=append_event_mock),
            patch("heartbeat.db.save_drives_state", new=AsyncMock()),
            patch("heartbeat.db.inbox_mark_read", new=AsyncMock()),
            patch("heartbeat.db.log_cycle", new=AsyncMock()),
            patch("heartbeat.db.transaction", new=lambda: _Tx()),
            patch("heartbeat.clock.now",
                  return_value=datetime(2026, 2, 16, 14, 0, 0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await hb.run_cycle('idle')

        # Nap was triggered
        nap_mock.assert_awaited_once()
        self.assertEqual(result['routing_focus'], 'nap')
        self.assertTrue(result.get('nap'))
        self.assertEqual(result['nap_moments_processed'], 2)
        self.assertIn('action_nap', result['actions'])

        # Nap event emitted
        append_event_mock.assert_awaited()

    async def test_nap_cooldown_enforced(self):
        """Budget exceeded + cooldown not elapsed -> skip, no empty loop."""
        hb = self._make_heartbeat()
        hb._last_nap_ts = clock.now_utc() - timedelta(minutes=30)  # only 30m ago

        mock_drives = types.SimpleNamespace(
            social_hunger=0.5, curiosity=0.5, expression_need=0.3,
            rest_need=0.4, energy=0.3, mood_valence=0.0, mood_arousal=0.5,
            copy=lambda self: types.SimpleNamespace(**self.__dict__),
        )
        mock_drives.copy = lambda: types.SimpleNamespace(**mock_drives.__dict__)

        mock_engagement = types.SimpleNamespace(
            status='none', visitor_id=None, turn_count=0,
            last_activity=None,
        )
        mock_routing = types.SimpleNamespace(
            cycle_type='idle', token_budget=3000, focus=None,
            memory_requests=[],
        )
        mock_perception = types.SimpleNamespace(
            salience=0.3, p_type='ambient', source='ambient',
            features={}, content='quiet',
        )

        nap_mock = AsyncMock(return_value=0)

        patches = [
            patch("heartbeat.db.inbox_get_unread",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.db.get_drives_state",
                  new=AsyncMock(return_value=mock_drives)),
            patch("heartbeat.update_drives",
                  new=AsyncMock(return_value=(mock_drives, []))),
            patch("heartbeat.build_perceptions",
                  new=AsyncMock(return_value=[mock_perception])),
            patch("heartbeat.perception_gate",
                  return_value=[mock_perception]),
            patch("heartbeat.apply_affect_lens",
                  return_value=[mock_perception]),
            patch("heartbeat.db.get_engagement_state",
                  new=AsyncMock(return_value=mock_engagement)),
            patch("heartbeat.route",
                  new=AsyncMock(return_value=mock_routing)),
            patch("heartbeat.recall",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.check_habits",
                  new=AsyncMock(return_value=None)),
            patch("heartbeat.db.get_energy_budget",
                  new=AsyncMock(return_value={'spent_today': 4.5, 'budget': 4.0})),
            patch("heartbeat.nap_consolidate", new=nap_mock),
            patch("heartbeat.db.save_drives_state", new=AsyncMock()),
            patch("heartbeat.db.inbox_mark_read", new=AsyncMock()),
            patch("heartbeat.db.log_cycle", new=AsyncMock()),
            patch("heartbeat.db.transaction", new=lambda: _Tx()),
            patch("heartbeat.clock.now",
                  return_value=datetime(2026, 2, 16, 14, 0, 0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await hb.run_cycle('idle')

        # Nap was NOT triggered (cooldown)
        nap_mock.assert_not_awaited()
        self.assertEqual(result['routing_focus'], 'rest')
        self.assertTrue(result.get('nap_cooldown'))
        self.assertGreater(result.get('nap_cooldown_remaining_min', 0), 0)

    async def test_nap_restores_partial_budget(self):
        """After nap, budget has +1.0 headroom."""
        hb = self._make_heartbeat()
        hb._last_nap_ts = None

        mock_drives = types.SimpleNamespace(
            social_hunger=0.5, curiosity=0.5, expression_need=0.3,
            rest_need=0.4, energy=0.3, mood_valence=0.0, mood_arousal=0.5,
            copy=lambda self: types.SimpleNamespace(**self.__dict__),
        )
        mock_drives.copy = lambda: types.SimpleNamespace(**mock_drives.__dict__)

        mock_engagement = types.SimpleNamespace(
            status='none', visitor_id=None, turn_count=0,
            last_activity=None,
        )
        mock_routing = types.SimpleNamespace(
            cycle_type='idle', token_budget=3000, focus=None,
            memory_requests=[],
        )
        mock_perception = types.SimpleNamespace(
            salience=0.3, p_type='ambient', source='ambient',
            features={}, content='quiet',
        )

        patches = [
            patch("heartbeat.db.inbox_get_unread",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.db.get_drives_state",
                  new=AsyncMock(return_value=mock_drives)),
            patch("heartbeat.update_drives",
                  new=AsyncMock(return_value=(mock_drives, []))),
            patch("heartbeat.build_perceptions",
                  new=AsyncMock(return_value=[mock_perception])),
            patch("heartbeat.perception_gate",
                  return_value=[mock_perception]),
            patch("heartbeat.apply_affect_lens",
                  return_value=[mock_perception]),
            patch("heartbeat.db.get_engagement_state",
                  new=AsyncMock(return_value=mock_engagement)),
            patch("heartbeat.route",
                  new=AsyncMock(return_value=mock_routing)),
            patch("heartbeat.recall",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.check_habits",
                  new=AsyncMock(return_value=None)),
            patch("heartbeat.db.get_energy_budget",
                  new=AsyncMock(return_value={'spent_today': 4.5, 'budget': 4.0})),
            patch("heartbeat.nap_consolidate",
                  new=AsyncMock(return_value=3)),
            patch("heartbeat.db.append_event", new=AsyncMock()),
            patch("heartbeat.db.save_drives_state", new=AsyncMock()),
            patch("heartbeat.db.inbox_mark_read", new=AsyncMock()),
            patch("heartbeat.db.log_cycle", new=AsyncMock()),
            patch("heartbeat.db.transaction", new=lambda: _Tx()),
            patch("heartbeat.clock.now",
                  return_value=datetime(2026, 2, 16, 14, 0, 0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        await hb.run_cycle('idle')

        # Budget bonus accumulated
        self.assertAlmostEqual(hb._nap_budget_bonus, 1.0)

    async def test_visitor_overrides_nap_cooldown(self):
        """High salience visitor event wakes her from nap cooldown."""
        hb = self._make_heartbeat()
        hb._last_nap_ts = clock.now_utc() - timedelta(minutes=30)

        mock_drives = types.SimpleNamespace(
            social_hunger=0.5, curiosity=0.5, expression_need=0.3,
            rest_need=0.4, energy=0.3, mood_valence=0.0, mood_arousal=0.5,
            copy=lambda self: types.SimpleNamespace(**self.__dict__),
        )
        mock_drives.copy = lambda: types.SimpleNamespace(**mock_drives.__dict__)

        mock_engagement = types.SimpleNamespace(
            status='none', visitor_id=None, turn_count=0,
            last_activity=None,
        )
        mock_routing = types.SimpleNamespace(
            cycle_type='idle', token_budget=3000, focus=None,
            memory_requests=[],
        )
        # High salience perception (visitor connect)
        mock_perception = types.SimpleNamespace(
            salience=0.9, p_type='visitor_connect', source='visitor:v1',
            features={}, content='visitor connected',
        )

        cortex_output = types.SimpleNamespace(
            internal_monologue='hello',
            dialogue='Welcome!',
            dialogue_language='en',
            expression='engaged',
            body_state='sitting',
            gaze='at_visitor',
            resonance=False,
            actions=[],
            memory_updates=[],
            next_cycle_hints=[],
            intentions=[],
        )

        mock_validated = MagicMock()
        mock_validated.internal_monologue = 'hello'
        mock_validated.dialogue = 'Welcome!'
        mock_validated.dialogue_language = 'en'
        mock_validated.expression = 'engaged'
        mock_validated.body_state = 'sitting'
        mock_validated.gaze = 'at_visitor'
        mock_validated.resonance = False
        mock_validated.actions = []
        mock_validated.memory_updates = []
        mock_validated.next_cycle_hints = []
        mock_validated.intentions = []
        mock_validated.approved_actions = []
        mock_validated.dropped_actions = []
        mock_validated.journal_deferred = False
        mock_validated.entropy_warning = None
        mock_validated.focus_pool_id = None
        mock_validated.to_dict = MagicMock(return_value={
            'internal_monologue': 'hello',
            'dialogue': 'Welcome!',
            'resonance': False,
            'actions': [],
            '_dropped_actions': [],
        })

        from models.pipeline import MotorPlan, BodyOutput

        patches = [
            patch("heartbeat.db.inbox_get_unread",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.db.get_drives_state",
                  new=AsyncMock(return_value=mock_drives)),
            patch("heartbeat.update_drives",
                  new=AsyncMock(return_value=(mock_drives, []))),
            patch("heartbeat.build_perceptions",
                  new=AsyncMock(return_value=[mock_perception])),
            patch("heartbeat.perception_gate",
                  return_value=[mock_perception]),
            patch("heartbeat.apply_affect_lens",
                  return_value=[mock_perception]),
            patch("heartbeat.db.get_engagement_state",
                  new=AsyncMock(return_value=mock_engagement)),
            patch("heartbeat.db.get_visitor", new=AsyncMock(return_value=None)),
            patch("heartbeat.route",
                  new=AsyncMock(return_value=mock_routing)),
            patch("heartbeat.recall",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.check_habits",
                  new=AsyncMock(return_value=None)),
            patch("heartbeat.db.get_energy_budget",
                  new=AsyncMock(return_value={'spent_today': 4.5, 'budget': 4.0})),
            # Cortex path — should be reached because high salience overrides
            patch("heartbeat.build_self_state",
                  new=AsyncMock(return_value=None)),
            patch("heartbeat.db.get_recent_conversation",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.cortex_call",
                  new=AsyncMock(return_value=cortex_output)),
            patch("heartbeat.validate", return_value=mock_validated),
            patch("heartbeat.select_actions",
                  new=AsyncMock(return_value=MotorPlan())),
            patch("heartbeat.execute_body",
                  new=AsyncMock(return_value=BodyOutput())),
            patch("heartbeat.process_output", new=AsyncMock()),
            patch("heartbeat.db.save_drives_state", new=AsyncMock()),
            patch("heartbeat.db.inbox_mark_read", new=AsyncMock()),
            patch("heartbeat.db.log_cycle", new=AsyncMock()),
            patch("heartbeat.db.transaction", new=lambda: _Tx()),
            patch("heartbeat.maybe_record_moment", new=AsyncMock()),
            patch("heartbeat.clock.now",
                  return_value=datetime(2026, 2, 16, 14, 0, 0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await hb.run_cycle('micro')

        # Should NOT be a nap or rest — cortex was called because high salience
        self.assertNotEqual(result.get('routing_focus'), 'nap')
        self.assertFalse(result.get('nap', False))
        self.assertFalse(result.get('nap_cooldown', False))

    async def test_no_empty_rest_loops(self):
        """Budget exceeded never produces token_budget=0 placeholder cycles
        with the old '(resting — energy budget exceeded)' monologue."""
        hb = self._make_heartbeat()
        hb._last_nap_ts = None

        mock_drives = types.SimpleNamespace(
            social_hunger=0.5, curiosity=0.5, expression_need=0.3,
            rest_need=0.4, energy=0.3, mood_valence=0.0, mood_arousal=0.5,
            copy=lambda self: types.SimpleNamespace(**self.__dict__),
        )
        mock_drives.copy = lambda: types.SimpleNamespace(**mock_drives.__dict__)

        mock_engagement = types.SimpleNamespace(
            status='none', visitor_id=None, turn_count=0,
            last_activity=None,
        )
        mock_routing = types.SimpleNamespace(
            cycle_type='idle', token_budget=3000, focus=None,
            memory_requests=[],
        )
        mock_perception = types.SimpleNamespace(
            salience=0.3, p_type='ambient', source='ambient',
            features={}, content='quiet',
        )

        patches = [
            patch("heartbeat.db.inbox_get_unread",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.db.get_drives_state",
                  new=AsyncMock(return_value=mock_drives)),
            patch("heartbeat.update_drives",
                  new=AsyncMock(return_value=(mock_drives, []))),
            patch("heartbeat.build_perceptions",
                  new=AsyncMock(return_value=[mock_perception])),
            patch("heartbeat.perception_gate",
                  return_value=[mock_perception]),
            patch("heartbeat.apply_affect_lens",
                  return_value=[mock_perception]),
            patch("heartbeat.db.get_engagement_state",
                  new=AsyncMock(return_value=mock_engagement)),
            patch("heartbeat.route",
                  new=AsyncMock(return_value=mock_routing)),
            patch("heartbeat.recall",
                  new=AsyncMock(return_value=[])),
            patch("heartbeat.check_habits",
                  new=AsyncMock(return_value=None)),
            patch("heartbeat.db.get_energy_budget",
                  new=AsyncMock(return_value={'spent_today': 4.5, 'budget': 4.0})),
            patch("heartbeat.nap_consolidate",
                  new=AsyncMock(return_value=2)),
            patch("heartbeat.db.append_event", new=AsyncMock()),
            patch("heartbeat.db.save_drives_state", new=AsyncMock()),
            patch("heartbeat.db.inbox_mark_read", new=AsyncMock()),
            patch("heartbeat.db.log_cycle", new=AsyncMock()),
            patch("heartbeat.db.transaction", new=lambda: _Tx()),
            patch("heartbeat.clock.now",
                  return_value=datetime(2026, 2, 16, 14, 0, 0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await hb.run_cycle('idle')

        # Should be nap, not the old empty rest
        self.assertNotEqual(
            result.get('internal_monologue'),
            '(resting — energy budget exceeded)'
        )
        self.assertFalse(result.get('budget_rest', False))


# ─── Nap Cooldown Helpers ───


class TestNapCooldownHelpers(unittest.TestCase):
    """Test Heartbeat nap cooldown calculation methods."""

    def test_nap_cooldown_elapsed_never_napped(self):
        hb = Heartbeat()
        hb._last_nap_ts = None
        self.assertTrue(hb._nap_cooldown_elapsed())

    def test_nap_cooldown_elapsed_long_ago(self):
        hb = Heartbeat()
        hb._last_nap_ts = clock.now_utc() - timedelta(hours=3)
        self.assertTrue(hb._nap_cooldown_elapsed())

    def test_nap_cooldown_not_elapsed(self):
        hb = Heartbeat()
        hb._last_nap_ts = clock.now_utc() - timedelta(minutes=30)
        self.assertFalse(hb._nap_cooldown_elapsed())

    def test_nap_cooldown_remaining_minutes(self):
        hb = Heartbeat()
        hb._last_nap_ts = clock.now_utc() - timedelta(minutes=90)
        remaining = hb._nap_cooldown_remaining_minutes()
        self.assertAlmostEqual(remaining, 30, delta=2)

    def test_nap_cooldown_remaining_zero_when_elapsed(self):
        hb = Heartbeat()
        hb._last_nap_ts = None
        self.assertEqual(hb._nap_cooldown_remaining_minutes(), 0)


if __name__ == '__main__':
    unittest.main()
