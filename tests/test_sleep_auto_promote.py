"""Tests for TASK-056 Phase 5: auto-promote pending actions during sleep_cycle.

Verifies:
1. promote_pending_actions is called with threshold=5 during sleep_cycle
2. Promoted actions are logged when the list is non-empty
"""

import types
import unittest
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import AsyncMock, patch

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

import db
import sleep


class _Tx:
    """Async context manager stub for db.transaction()."""
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_sleep_cycle_patches(promote_mock: AsyncMock) -> list:
    """Build the full patch list needed to run sleep_cycle without a real DB.

    Mirrors the pattern in test_hollow_sleep.TestSleepProcessesRemaining,
    plus the new promote_pending_actions mock for TASK-056.
    """
    moderate_moment = types.SimpleNamespace(
        id='m-moderate', retry_count=0, visitor_id=None,
        summary='A quiet moment.',
        moment_type='resonance', tags=[],
        ts=datetime(2026, 2, 17, 14, 0, tzinfo=timezone.utc),
        salience=0.50,
    )
    return [
        patch.object(sleep.db, 'get_engagement_state',
                     new=AsyncMock(return_value=types.SimpleNamespace(status='none'))),
        patch.object(sleep.db, 'get_unprocessed_day_memory',
                     new=AsyncMock(return_value=[moderate_moment])),
        patch.object(sleep, 'gather_hot_context', new=AsyncMock(return_value={})),
        patch.object(sleep, 'sleep_reflect',
                     new=AsyncMock(return_value={'reflection': 'ok', 'memory_updates': []})),
        patch.object(sleep.db, 'transaction', new=lambda: _Tx()),
        patch.object(sleep.db, 'insert_journal', new=AsyncMock(return_value='j1')),
        patch.object(sleep.db, 'mark_day_memory_processed', new=AsyncMock()),
        patch.object(sleep, 'write_daily_summary', new=AsyncMock()),
        patch.object(sleep, 'review_trait_stability', new=AsyncMock()),
        patch.object(sleep, 'review_self_modifications', new=AsyncMock()),
        patch.object(sleep, 'manage_thread_lifecycle', new=AsyncMock()),
        patch.object(sleep, 'cleanup_content_pool', new=AsyncMock()),
        patch.object(sleep, 'reset_drives_for_morning', new=AsyncMock()),
        patch.object(sleep, 'flush_day_memory', new=AsyncMock()),
        patch.object(sleep.db, 'set_setting', new=AsyncMock()),
        patch.object(sleep.db, 'promote_pending_actions', new=promote_mock),
    ]


class TestAutoPromoteCalledDuringSleepCycle(unittest.IsolatedAsyncioTestCase):
    """promote_pending_actions is called with threshold=5 during sleep_cycle."""

    async def test_auto_promote_called_during_sleep_cycle(self):
        """sleep_cycle must call db.promote_pending_actions(threshold=5)."""
        promote_mock = AsyncMock(return_value=[])
        patches = _make_sleep_cycle_patches(promote_mock)
        for pat in patches:
            pat.start()
        try:
            await sleep.sleep_cycle()
            promote_mock.assert_called_once_with(threshold=5)
        finally:
            for pat in patches:
                pat.stop()


class TestPromotesAreLogged(unittest.IsolatedAsyncioTestCase):
    """When promote_pending_actions returns actions, they are printed."""

    async def test_promotes_are_logged(self):
        """When promoted list is non-empty, a [Sleep] message is printed."""
        promoted_actions = [
            {'action_name': 'bow', 'status': 'promoted', 'attempt_count': 7},
            {'action_name': 'wave', 'status': 'promoted', 'attempt_count': 5},
        ]
        promote_mock = AsyncMock(return_value=promoted_actions)
        patches = _make_sleep_cycle_patches(promote_mock)
        for pat in patches:
            pat.start()
        try:
            with patch('builtins.print') as mock_print:
                await sleep.sleep_cycle()

            # Collect all print call args into a single string for easy search
            all_output = ' '.join(
                str(arg)
                for call in mock_print.call_args_list
                for arg in call[0]
            )
            assert '[Sleep] Auto-promoted' in all_output, (
                f"Expected '[Sleep] Auto-promoted' in print output, got:\n{all_output}"
            )
            assert 'bow' in all_output, (
                f"Expected action name 'bow' in print output"
            )
            assert 'wave' in all_output, (
                f"Expected action name 'wave' in print output"
            )
        finally:
            for pat in patches:
                pat.stop()

    async def test_no_log_when_empty(self):
        """When promoted list is empty, no auto-promote message is printed."""
        promote_mock = AsyncMock(return_value=[])
        patches = _make_sleep_cycle_patches(promote_mock)
        for pat in patches:
            pat.start()
        try:
            with patch('builtins.print') as mock_print:
                await sleep.sleep_cycle()

            all_output = ' '.join(
                str(arg)
                for call in mock_print.call_args_list
                for arg in call[0]
            )
            assert '[Sleep] Auto-promoted' not in all_output, (
                f"Expected no '[Sleep] Auto-promoted' when nothing was promoted"
            )
        finally:
            for pat in patches:
                pat.stop()
