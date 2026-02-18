"""Tests for TASK-064: Sleep phase extraction.

Verifies each extracted phase module is independently testable and that
the package structure preserves backward compatibility.

Phase modules tested:
1. sleep.reflection  — gather_hot_context, format_traits_for_sleep, sleep_reflect,
                       write_daily_summary, compute_emotional_arc_from_moments,
                       extract_totems_from_reflections
2. sleep.nap         — nap_consolidate
3. sleep.meta_review — review_trait_stability, review_self_modifications, run_meta_review
4. sleep.wake        — reset_drives_for_morning, flush_day_memory,
                       manage_thread_lifecycle, cleanup_content_pool, run_wake_transition
5. sleep.consolidation — run_consolidation
"""

import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

import sleep
from sleep.reflection import (
    gather_hot_context,
    format_traits_for_sleep,
    compute_emotional_arc_from_moments,
    extract_totems_from_reflections,
)
from sleep.meta_review import _CATEGORY_DRIVE_MAP
from sleep.wake import (
    reset_drives_for_morning,
    flush_day_memory,
    manage_thread_lifecycle,
    cleanup_content_pool,
)


# ─── Helpers ───

class _Tx:
    """Async context manager stub for db.transaction()."""
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


# ─── 1. sleep.reflection tests ───

class TestGatherHotContext(unittest.IsolatedAsyncioTestCase):
    """gather_hot_context assembles memory context without LLM calls."""

    async def test_empty_context_when_no_visitor(self):
        """Moment with no visitor_id and no tags produces minimal context."""
        import sleep.reflection as _ref
        moment = types.SimpleNamespace(
            id='m1', retry_count=0, visitor_id=None,
            summary='quiet moment', moment_type='idle',
            tags=None,  # None, not [], to avoid _moment default
            ts=datetime(2026, 2, 10, tzinfo=timezone.utc),
            salience=0.5,
        )
        with patch.object(_ref.db, 'get_recent_journal',
                          new=AsyncMock(return_value=[])):
            ctx = await gather_hot_context(moment)
        self.assertNotIn('visitor', ctx)
        self.assertNotIn('traits', ctx)

    async def test_visitor_context_populated(self):
        """Moment with visitor_id gathers visitor, traits, totems."""
        import sleep.reflection as _ref
        moment = _moment(visitor_id='v1', tags=[])
        visitor = types.SimpleNamespace(
            id='v1', name='Yuki', visit_count=3,
            first_visit='2026-01-01', last_visit='2026-02-10',
            trust_level='returner', emotional_imprint=None, summary=None,
        )
        trait = types.SimpleNamespace(
            trait_category='personality', trait_key='humor',
            trait_value='dry', stability=0.8,
            status='confirmed', id='t1', visitor_id='v1',
            observed_at=datetime.now(timezone.utc),
        )
        totem = types.SimpleNamespace(entity='Nujabes', weight=0.9, context=None)

        patches = [
            patch.object(_ref.db, 'get_visitor',
                         new=AsyncMock(return_value=visitor)),
            patch.object(_ref.db, 'get_visitor_traits',
                         new=AsyncMock(return_value=[trait])),
            patch.object(_ref.db, 'get_totems',
                         new=AsyncMock(return_value=[totem])),
            patch.object(_ref.db, 'search_collection',
                         new=AsyncMock(return_value=[])),
            patch.object(_ref.db, 'get_recent_journal',
                         new=AsyncMock(return_value=[])),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        ctx = await gather_hot_context(moment)
        self.assertIn('visitor', ctx)
        self.assertIn('traits', ctx)
        self.assertIn('totems', ctx)


class TestFormatTraitsForSleep(unittest.TestCase):
    """format_traits_for_sleep deduplicates and formats traits."""

    def test_deduplicates_by_key(self):
        """Only first occurrence of each trait_key is kept."""
        traits = [
            types.SimpleNamespace(trait_category='a', trait_key='k1', trait_value='v1'),
            types.SimpleNamespace(trait_category='a', trait_key='k1', trait_value='v2'),
            types.SimpleNamespace(trait_category='b', trait_key='k2', trait_value='v3'),
        ]
        result = format_traits_for_sleep(traits)
        self.assertEqual(result.count('k1'), 1)
        self.assertIn('k2', result)

    def test_empty_traits(self):
        result = format_traits_for_sleep([])
        self.assertEqual(result, "")


class TestComputeEmotionalArc(unittest.TestCase):
    """compute_emotional_arc_from_moments derives arc from moment types."""

    def test_empty_moments_returns_quiet(self):
        self.assertEqual(compute_emotional_arc_from_moments([]), 'quiet')

    def test_deduplicates_preserving_order(self):
        moments = [
            _moment(moment_type='conversation'),
            _moment(moment_type='discovery'),
            _moment(moment_type='conversation'),
        ]
        arc = compute_emotional_arc_from_moments(moments)
        self.assertEqual(arc, 'conversation -> discovery')


class TestExtractTotems(unittest.TestCase):
    """extract_totems_from_reflections pulls totem entities."""

    def test_extracts_totem_entities(self):
        reflections = [
            {'moment': _moment(), 'reflection': {'memory_updates': [
                {'type': 'totem_create', 'content': {'entity': 'Nujabes'}},
                {'type': 'trait_update', 'content': {'key': 'humor'}},
            ]}},
            {'moment': _moment(), 'reflection': {'memory_updates': [
                {'type': 'totem_update', 'content': {'entity': 'rain'}},
            ]}},
        ]
        totems = extract_totems_from_reflections(reflections)
        self.assertEqual(totems, ['Nujabes', 'rain'])

    def test_no_totems_returns_empty(self):
        reflections = [
            {'moment': _moment(), 'reflection': {'memory_updates': []}},
        ]
        self.assertEqual(extract_totems_from_reflections(reflections), [])


# ─── 2. sleep.meta_review tests ───

class TestCategoryDriveMap(unittest.TestCase):
    """_CATEGORY_DRIVE_MAP is correctly structured."""

    def test_all_categories_present(self):
        expected = {'hypothalamus', 'thalamus', 'sensorium', 'basal_ganglia', 'output', 'sleep'}
        self.assertEqual(set(_CATEGORY_DRIVE_MAP.keys()), expected)

    def test_all_values_are_lists(self):
        for cat, drives in _CATEGORY_DRIVE_MAP.items():
            self.assertIsInstance(drives, list, f"{cat} should map to a list")


class TestRunMetaReview(unittest.IsolatedAsyncioTestCase):
    """run_meta_review calls all three sub-phases."""

    async def test_calls_all_phases(self):
        """run_meta_review calls trait stability, self-mod review, and auto-promote."""
        from sleep.meta_review import run_meta_review

        with patch.object(sleep, 'review_trait_stability', new=AsyncMock()) as mock_traits, \
             patch.object(sleep, 'review_self_modifications', new=AsyncMock()) as mock_mods, \
             patch.object(sleep.db, 'promote_pending_actions', new=AsyncMock(return_value=[])) as mock_promote:
            await run_meta_review()
            mock_traits.assert_awaited_once()
            mock_mods.assert_awaited_once()
            mock_promote.assert_awaited_once_with(threshold=5)


# ─── 3. sleep.wake tests ───

class TestResetDrivesForMorning(unittest.IsolatedAsyncioTestCase):
    """reset_drives_for_morning sets drive values to morning defaults."""

    async def test_resets_drives(self):
        from models.state import DrivesState
        drives = DrivesState(
            social_hunger=0.9, curiosity=0.1, expression_need=0.9,
            rest_need=0.8, energy=0.2,
        )
        save_mock = AsyncMock()
        with patch.object(sleep.db, 'get_drives_state',
                          new=AsyncMock(return_value=drives)), \
             patch.object(sleep.db, 'save_drives_state', new=save_mock):
            await reset_drives_for_morning()

        save_mock.assert_awaited_once()
        saved = save_mock.await_args[0][0]
        # Morning defaults from self_parameters
        self.assertIsNotNone(saved.social_hunger)
        self.assertIsNotNone(saved.energy)


class TestFlushDayMemory(unittest.IsolatedAsyncioTestCase):
    """flush_day_memory calls both cleanup functions."""

    async def test_calls_both_cleanups(self):
        delete_processed = AsyncMock()
        delete_stale = AsyncMock()
        with patch.object(sleep.db, 'delete_processed_day_memory', new=delete_processed), \
             patch.object(sleep.db, 'delete_stale_day_memory', new=delete_stale):
            await flush_day_memory()
        delete_processed.assert_awaited_once()
        delete_stale.assert_awaited_once()


class TestManageThreadLifecycle(unittest.IsolatedAsyncioTestCase):
    """manage_thread_lifecycle handles dormant and archive transitions."""

    async def test_dormant_threads_transitioned(self):
        thread = types.SimpleNamespace(id='t1', status='open')
        touch_mock = AsyncMock()
        archive_mock = AsyncMock(return_value=0)

        with patch.object(sleep.db, 'get_dormant_threads',
                          new=AsyncMock(return_value=[thread])), \
             patch.object(sleep.db, 'touch_thread', new=touch_mock), \
             patch.object(sleep.db, 'archive_stale_threads', new=archive_mock):
            await manage_thread_lifecycle()

        touch_mock.assert_awaited_once()
        call_kwargs = touch_mock.await_args[1]
        self.assertEqual(call_kwargs['status'], 'dormant')

    async def test_no_threads_no_error(self):
        with patch.object(sleep.db, 'get_dormant_threads',
                          new=AsyncMock(return_value=[])), \
             patch.object(sleep.db, 'archive_stale_threads',
                          new=AsyncMock(return_value=0)):
            await manage_thread_lifecycle()  # should not raise


class TestCleanupContentPool(unittest.IsolatedAsyncioTestCase):
    """cleanup_content_pool expires and caps pool items."""

    async def test_calls_both_cleanups(self):
        expire_mock = AsyncMock()
        cap_mock = AsyncMock()
        with patch.object(sleep.db, 'expire_pool_items', new=expire_mock), \
             patch.object(sleep.db, 'cap_unseen_pool', new=cap_mock):
            await cleanup_content_pool()
        expire_mock.assert_awaited_once()
        cap_mock.assert_awaited_once()


# ─── 4. Package structure tests ───

class TestPackageStructure(unittest.TestCase):
    """Verify the sleep package exports all expected names."""

    def test_sleep_cycle_exported(self):
        self.assertTrue(callable(sleep.sleep_cycle))

    def test_nap_consolidate_exported(self):
        self.assertTrue(callable(sleep.nap_consolidate))

    def test_all_helpers_exported(self):
        """All function names that existed on the old sleep module are accessible."""
        expected_names = [
            'sleep_cycle', 'nap_consolidate',
            'gather_hot_context', 'format_traits_for_sleep',
            'sleep_reflect', 'write_daily_summary',
            'compute_emotional_arc_from_moments', 'extract_totems_from_reflections',
            'review_trait_stability', 'review_self_modifications',
            'manage_thread_lifecycle', 'cleanup_content_pool',
            'reset_drives_for_morning', 'flush_day_memory',
            '_CATEGORY_DRIVE_MAP',
            'cortex_call_reflect', 'SLEEP_REFLECTION_SYSTEM',
            'hippocampus_consolidate',
            'COLD_SEARCH_ENABLED',
        ]
        for name in expected_names:
            self.assertTrue(hasattr(sleep, name),
                            f"sleep.{name} not exported from package")

    def test_db_and_clock_accessible(self):
        """Tests that patch sleep.db and sleep.clock still work."""
        import db as _db
        import clock as _clock
        self.assertTrue(hasattr(sleep, 'db'))
        self.assertTrue(hasattr(sleep, 'clock'))
        # Verify they're the real modules (not already patched)
        self.assertEqual(sleep.db.__name__, 'db')
        self.assertEqual(sleep.clock.__name__, 'clock')


# ─── 5. sleep.consolidation tests ───

class TestRunConsolidation(unittest.IsolatedAsyncioTestCase):
    """run_consolidation processes moments and writes daily summary."""

    async def test_quiet_day_returns_zero(self):
        """When no moments exist and no summary yet, writes quiet entry and returns 0."""
        import sleep.consolidation as _consol
        from sleep.consolidation import run_consolidation

        patches = [
            patch.object(_consol.db, 'get_unprocessed_day_memory',
                         new=AsyncMock(return_value=[])),
            patch.object(_consol.db, 'get_daily_summary_for_today',
                         new=AsyncMock(return_value=None)),
            patch.object(_consol.db, 'insert_journal', new=AsyncMock(return_value='j1')),
            patch.object(sleep, 'write_daily_summary', new=AsyncMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await run_consolidation()
        self.assertEqual(result, 0)

    async def test_processes_moments_returns_count(self):
        """When moments exist, processes them and returns count."""
        import sleep.consolidation as _consol
        from sleep.consolidation import run_consolidation

        moments = [_moment(id='m1'), _moment(id='m2')]

        patches = [
            patch.object(_consol.db, 'get_unprocessed_day_memory',
                         new=AsyncMock(return_value=moments)),
            patch.object(sleep, 'gather_hot_context', new=AsyncMock(return_value={})),
            patch.object(sleep, 'sleep_reflect',
                         new=AsyncMock(return_value={'reflection': 'ok', 'memory_updates': []})),
            patch.object(_consol.db, 'transaction', new=lambda: _Tx()),
            patch.object(_consol.db, 'insert_journal', new=AsyncMock(return_value='j1')),
            patch.object(_consol.db, 'mark_day_memory_processed', new=AsyncMock()),
            patch.object(sleep, 'write_daily_summary', new=AsyncMock()),
            patch.object(sleep, 'hippocampus_consolidate', new=AsyncMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = await run_consolidation()
        self.assertEqual(result, 2)
