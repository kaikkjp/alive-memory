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


# ─── Heartbeat Nap Trigger Tests (TASK-050: heartbeat nap removed) ───
# TASK-050 removed nap consolidation from heartbeat.run_cycle.
# Budget check replaces the old nap system. When budget is exhausted,
# the cycle rests at normal interval instead of napping.
# Tests below are REMOVED (tested removed behavior):
# - test_nap_triggers_on_budget_exceeded
# - test_nap_cooldown_enforced
# - test_nap_restores_partial_budget
# - test_visitor_overrides_nap_cooldown
# - test_no_empty_rest_loops
# - TestNapCooldownHelpers


if __name__ == '__main__':
    unittest.main()
