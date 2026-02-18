import json
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, call

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

from pipeline import cold_search as cold_search_mod
from pipeline import embed_cold as embed_cold_mod
import sleep
from db import _row_to_daily_summary
from db.parameters import p
from models.state import DailySummary


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class SleepColdMemoryTests(unittest.IsolatedAsyncioTestCase):
    def _moment(self, id="m1", salience=0.8):
        return types.SimpleNamespace(
            id=id,
            retry_count=0,
            visitor_id="v1",
            summary="today summary",
            moment_type="conversation",
            tags=["music"],
            ts=datetime(2026, 2, 10, tzinfo=timezone.utc),
            salience=salience,
        )

    async def _run_sleep_cycle_with_common_patches(self):
        self._insert_journal_mock = AsyncMock(return_value="journal-id-1")
        patches = [
            patch.object(sleep.db, "get_engagement_state", new=AsyncMock(return_value=types.SimpleNamespace(status="none"))),
            patch.object(sleep.db, "get_unprocessed_day_memory", new=AsyncMock(return_value=[self._moment()])),
            patch.object(sleep, "gather_hot_context", new=AsyncMock(return_value={})),
            patch.object(sleep, "sleep_reflect", new=AsyncMock(return_value={"memory_updates": [], "reflection": "ok"})),
            patch.object(sleep, "write_daily_summary", new=AsyncMock()),
            patch.object(sleep, "review_trait_stability", new=AsyncMock()),
            patch.object(sleep, "review_self_modifications", new=AsyncMock()),
            patch.object(sleep.db, "promote_pending_actions", new=AsyncMock(return_value=[])),
            patch.object(sleep, "manage_thread_lifecycle", new=AsyncMock()),
            patch.object(sleep, "cleanup_content_pool", new=AsyncMock()),
            patch.object(sleep, "reset_drives_for_morning", new=AsyncMock()),
            patch.object(sleep, "flush_day_memory", new=AsyncMock()),
            patch.object(sleep.db, "mark_day_memory_processed", new=AsyncMock()),
            patch.object(sleep.db, "increment_day_memory_retry", new=AsyncMock()),
            patch.object(sleep.db, "insert_journal", new=self._insert_journal_mock),
            patch.object(sleep, "hippocampus_consolidate", new=AsyncMock()),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
            patch.object(sleep.db, "set_setting", new=AsyncMock()),
        ]
        for pat in patches:
            pat.start()
            self.addCleanup(pat.stop)
        with patch.object(sleep, "COLD_SEARCH_ENABLED", True):
            return await sleep.sleep_cycle()

    async def test_sleep_cycle_continues_when_cold_search_raises(self):
        with patch.object(cold_search_mod, "search_cold_memory", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with patch.object(
                embed_cold_mod,
                "embed_new_cold_entries",
                new=AsyncMock(
                    return_value={
                        "conversations_embedded": 0,
                        "monologues_embedded": 0,
                        "errors": 0,
                    }
                ),
            ):
                result = await self._run_sleep_cycle_with_common_patches()
        self.assertTrue(result)

    async def test_sleep_cycle_continues_when_embedding_pipeline_raises(self):
        with patch.object(cold_search_mod, "search_cold_memory", new=AsyncMock(return_value=[])):
            with patch.object(embed_cold_mod, "embed_new_cold_entries", new=AsyncMock(side_effect=RuntimeError("boom"))):
                result = await self._run_sleep_cycle_with_common_patches()
        self.assertTrue(result)

    async def test_sleep_reflect_prompt_includes_cold_echo_summary_and_context(self):
        moment = self._moment()
        cold_echoes = [
            {
                "date": "2026-02-01",
                "summary": "older related memory",
                "context": "past exchange snippet",
            }
        ]
        with patch.object(sleep, "cortex_call_reflect", new=AsyncMock(return_value={"ok": True})) as call_reflect:
            await sleep.sleep_reflect(moment, hot_context={}, cold_echoes=cold_echoes)

        prompt = call_reflect.await_args.kwargs["prompt"]
        self.assertIn("[2026-02-01] older related memory", prompt)
        self.assertIn("Context: past exchange snippet", prompt)


class SleepReflectiveJournalTests(unittest.IsolatedAsyncioTestCase):
    """Tests for TASK-007: Sleep tuning — reflective not summarizing.

    Verifies:
    1. Each moment produces its own journal entry (not one concatenated blob).
    2. Daily summary is a lightweight index (moment IDs, journal entry IDs, emotional arc).
    3. Moments below 0.65 salience are not reflected on.
    """

    def _moment(self, id="m1", salience=0.8, moment_type="conversation",
                tags=None, visitor_id="v1"):
        return types.SimpleNamespace(
            id=id,
            retry_count=0,
            visitor_id=visitor_id,
            summary=f"summary for {id}",
            moment_type=moment_type,
            tags=tags or ["music"],
            ts=datetime(2026, 2, 10, tzinfo=timezone.utc),
            salience=salience,
        )

    async def test_min_sleep_salience_is_0_45(self):
        """MIN_SLEEP_SALIENCE should be 0.45 (TASK-047 threshold hierarchy)."""
        self.assertEqual(p('sleep.consolidation.min_salience'), 0.45)

    async def test_each_moment_gets_own_journal_entry(self):
        """Each reflected moment should produce its own journal entry."""
        moments = [
            self._moment(id="m1", moment_type="conversation"),
            self._moment(id="m2", moment_type="discovery"),
            self._moment(id="m3", moment_type="emotional"),
        ]

        call_count = 0
        async def mock_insert_journal(content, mood=None, tags=None, day_alive=None):
            nonlocal call_count
            call_count += 1
            return f"journal-{call_count}"

        insert_journal_mock = AsyncMock(side_effect=mock_insert_journal)

        patches = [
            patch.object(sleep.db, "get_engagement_state", new=AsyncMock(return_value=types.SimpleNamespace(status="none"))),
            patch.object(sleep.db, "get_unprocessed_day_memory", new=AsyncMock(return_value=moments)),
            patch.object(sleep, "gather_hot_context", new=AsyncMock(return_value={})),
            patch.object(sleep, "sleep_reflect", new=AsyncMock(return_value={
                "memory_updates": [], "reflection": "I reflected on this moment"
            })),
            patch.object(sleep, "write_daily_summary", new=AsyncMock()),
            patch.object(sleep, "review_trait_stability", new=AsyncMock()),
            patch.object(sleep, "review_self_modifications", new=AsyncMock()),
            patch.object(sleep.db, "promote_pending_actions", new=AsyncMock(return_value=[])),
            patch.object(sleep, "manage_thread_lifecycle", new=AsyncMock()),
            patch.object(sleep, "cleanup_content_pool", new=AsyncMock()),
            patch.object(sleep, "reset_drives_for_morning", new=AsyncMock()),
            patch.object(sleep, "flush_day_memory", new=AsyncMock()),
            patch.object(sleep.db, "mark_day_memory_processed", new=AsyncMock()),
            patch.object(sleep.db, "increment_day_memory_retry", new=AsyncMock()),
            patch.object(sleep.db, "insert_journal", new=insert_journal_mock),
            patch.object(sleep, "hippocampus_consolidate", new=AsyncMock()),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
            patch.object(sleep.db, "set_setting", new=AsyncMock()),
        ]
        for pat in patches:
            pat.start()
            self.addCleanup(pat.stop)

        await sleep.sleep_cycle()

        # 3 moments → 3 individual journal entries
        self.assertEqual(insert_journal_mock.await_count, 3)

        # Each journal entry should have 'sleep_reflection' tag + moment type
        for c in insert_journal_mock.await_args_list:
            tags = c.kwargs.get('tags', [])
            self.assertIn('sleep_reflection', tags)
            self.assertEqual(c.kwargs.get('mood'), 'reflective')

    async def test_daily_summary_is_lightweight_index(self):
        """Daily summary should contain moment IDs and journal entry IDs, not narrative text."""
        moments = [
            self._moment(id="m1"),
            self._moment(id="m2"),
        ]

        call_count = 0
        async def mock_insert_journal(content, mood=None, tags=None, day_alive=None):
            nonlocal call_count
            call_count += 1
            return f"journal-{call_count}"

        write_summary_mock = AsyncMock()
        insert_journal_mock = AsyncMock(side_effect=mock_insert_journal)

        patches = [
            patch.object(sleep.db, "get_engagement_state", new=AsyncMock(return_value=types.SimpleNamespace(status="none"))),
            patch.object(sleep.db, "get_unprocessed_day_memory", new=AsyncMock(return_value=moments)),
            patch.object(sleep, "gather_hot_context", new=AsyncMock(return_value={})),
            patch.object(sleep, "sleep_reflect", new=AsyncMock(return_value={
                "memory_updates": [], "reflection": "I reflected"
            })),
            patch.object(sleep, "write_daily_summary", new=write_summary_mock),
            patch.object(sleep, "review_trait_stability", new=AsyncMock()),
            patch.object(sleep, "review_self_modifications", new=AsyncMock()),
            patch.object(sleep.db, "promote_pending_actions", new=AsyncMock(return_value=[])),
            patch.object(sleep, "manage_thread_lifecycle", new=AsyncMock()),
            patch.object(sleep, "cleanup_content_pool", new=AsyncMock()),
            patch.object(sleep, "reset_drives_for_morning", new=AsyncMock()),
            patch.object(sleep, "flush_day_memory", new=AsyncMock()),
            patch.object(sleep.db, "mark_day_memory_processed", new=AsyncMock()),
            patch.object(sleep.db, "increment_day_memory_retry", new=AsyncMock()),
            patch.object(sleep.db, "insert_journal", new=insert_journal_mock),
            patch.object(sleep, "hippocampus_consolidate", new=AsyncMock()),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
            patch.object(sleep.db, "set_setting", new=AsyncMock()),
        ]
        for pat in patches:
            pat.start()
            self.addCleanup(pat.stop)

        await sleep.sleep_cycle()

        # write_daily_summary should be called with (moments, reflections, journal_entry_ids)
        write_summary_mock.assert_awaited_once()
        args = write_summary_mock.await_args[0]
        passed_moments = args[0]
        passed_journal_ids = args[2]

        self.assertEqual(len(passed_moments), 2)
        self.assertEqual(passed_journal_ids, ["journal-1", "journal-2"])

    async def test_write_daily_summary_produces_index_not_narrative(self):
        """write_daily_summary should call insert_daily_summary with index structure."""
        moments = [
            self._moment(id="m1", moment_type="conversation"),
            self._moment(id="m2", moment_type="discovery"),
        ]
        reflections = [
            {'moment': moments[0], 'reflection': {"reflection": "r1", "memory_updates": []}},
            {'moment': moments[1], 'reflection': {"reflection": "r2", "memory_updates": []}},
        ]
        journal_ids = ["j1", "j2"]

        insert_summary_mock = AsyncMock()
        patches = [
            patch.object(sleep.db, "get_days_alive", new=AsyncMock(return_value=42)),
            patch.object(sleep.db, "insert_daily_summary", new=insert_summary_mock),
            patch.object(sleep.clock, "now", return_value=datetime(2026, 2, 14, 12, 0, 0)),
        ]
        for pat in patches:
            pat.start()
            self.addCleanup(pat.stop)

        await sleep.write_daily_summary(moments, reflections, journal_ids)

        insert_summary_mock.assert_awaited_once()
        summary = insert_summary_mock.await_args[0][0]

        # Should have index fields, not narrative
        self.assertEqual(summary['moment_count'], 2)
        self.assertEqual(summary['moment_ids'], ["m1", "m2"])
        self.assertEqual(summary['journal_entry_ids'], ["j1", "j2"])
        self.assertEqual(summary['emotional_arc'], 'conversation -> discovery')
        self.assertNotIn('summary_bullets', summary)
        self.assertNotIn('journal_entry_id', summary)

    async def test_journal_entries_tagged_with_moment_type(self):
        """Each journal entry should include the moment type in its tags."""
        moments = [
            self._moment(id="m1", moment_type="conversation", tags=["music"]),
            self._moment(id="m2", moment_type="discovery", tags=["art"]),
        ]

        insert_journal_mock = AsyncMock(return_value="j1")

        patches = [
            patch.object(sleep.db, "get_engagement_state", new=AsyncMock(return_value=types.SimpleNamespace(status="none"))),
            patch.object(sleep.db, "get_unprocessed_day_memory", new=AsyncMock(return_value=moments)),
            patch.object(sleep, "gather_hot_context", new=AsyncMock(return_value={})),
            patch.object(sleep, "sleep_reflect", new=AsyncMock(return_value={
                "memory_updates": [], "reflection": "reflected"
            })),
            patch.object(sleep, "write_daily_summary", new=AsyncMock()),
            patch.object(sleep, "review_trait_stability", new=AsyncMock()),
            patch.object(sleep, "review_self_modifications", new=AsyncMock()),
            patch.object(sleep.db, "promote_pending_actions", new=AsyncMock(return_value=[])),
            patch.object(sleep, "manage_thread_lifecycle", new=AsyncMock()),
            patch.object(sleep, "cleanup_content_pool", new=AsyncMock()),
            patch.object(sleep, "reset_drives_for_morning", new=AsyncMock()),
            patch.object(sleep, "flush_day_memory", new=AsyncMock()),
            patch.object(sleep.db, "mark_day_memory_processed", new=AsyncMock()),
            patch.object(sleep.db, "increment_day_memory_retry", new=AsyncMock()),
            patch.object(sleep.db, "insert_journal", new=insert_journal_mock),
            patch.object(sleep, "hippocampus_consolidate", new=AsyncMock()),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
            patch.object(sleep.db, "set_setting", new=AsyncMock()),
        ]
        for pat in patches:
            pat.start()
            self.addCleanup(pat.stop)

        await sleep.sleep_cycle()

        # First call: moment type "conversation" with tags ["music"]
        first_call_tags = insert_journal_mock.await_args_list[0].kwargs['tags']
        self.assertIn('sleep_reflection', first_call_tags)
        self.assertIn('conversation', first_call_tags)
        self.assertIn('music', first_call_tags)

        # Second call: moment type "discovery" with tags ["art"]
        second_call_tags = insert_journal_mock.await_args_list[1].kwargs['tags']
        self.assertIn('sleep_reflection', second_call_tags)
        self.assertIn('discovery', second_call_tags)
        self.assertIn('art', second_call_tags)

    async def test_empty_reflection_text_skips_journal_entry(self):
        """If a reflection has no text, no journal entry should be written for it."""
        moments = [self._moment(id="m1")]

        insert_journal_mock = AsyncMock(return_value="j1")

        patches = [
            patch.object(sleep.db, "get_engagement_state", new=AsyncMock(return_value=types.SimpleNamespace(status="none"))),
            patch.object(sleep.db, "get_unprocessed_day_memory", new=AsyncMock(return_value=moments)),
            patch.object(sleep, "gather_hot_context", new=AsyncMock(return_value={})),
            patch.object(sleep, "sleep_reflect", new=AsyncMock(return_value={
                "memory_updates": [], "reflection": ""
            })),
            patch.object(sleep, "write_daily_summary", new=AsyncMock()),
            patch.object(sleep, "review_trait_stability", new=AsyncMock()),
            patch.object(sleep, "review_self_modifications", new=AsyncMock()),
            patch.object(sleep.db, "promote_pending_actions", new=AsyncMock(return_value=[])),
            patch.object(sleep, "manage_thread_lifecycle", new=AsyncMock()),
            patch.object(sleep, "cleanup_content_pool", new=AsyncMock()),
            patch.object(sleep, "reset_drives_for_morning", new=AsyncMock()),
            patch.object(sleep, "flush_day_memory", new=AsyncMock()),
            patch.object(sleep.db, "mark_day_memory_processed", new=AsyncMock()),
            patch.object(sleep.db, "increment_day_memory_retry", new=AsyncMock()),
            patch.object(sleep.db, "insert_journal", new=insert_journal_mock),
            patch.object(sleep, "hippocampus_consolidate", new=AsyncMock()),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
            patch.object(sleep.db, "set_setting", new=AsyncMock()),
        ]
        for pat in patches:
            pat.start()
            self.addCleanup(pat.stop)

        await sleep.sleep_cycle()

        # Empty reflection → no journal entry written
        insert_journal_mock.assert_not_awaited()


class DailySummaryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    """TASK-016: Verify DailySummary dataclass matches the new index schema."""

    def test_daily_summary_has_index_fields(self):
        """DailySummary should have moment_count, moment_ids, journal_entry_ids."""
        ds = DailySummary(id="ds1")
        self.assertEqual(ds.moment_count, 0)
        self.assertEqual(ds.moment_ids, [])
        self.assertEqual(ds.journal_entry_ids, [])
        self.assertIsNone(ds.emotional_arc)
        self.assertEqual(ds.notable_totems, [])

    def test_daily_summary_no_legacy_fields(self):
        """DailySummary should NOT have the old summary_bullets or journal_entry_id fields."""
        ds = DailySummary(id="ds1")
        self.assertFalse(hasattr(ds, 'summary_bullets'))
        self.assertFalse(hasattr(ds, 'journal_entry_id'))

    def test_daily_summary_round_trip_via_db_helper(self):
        """_row_to_daily_summary should unpack the legacy summary_bullets JSON
        into the new DailySummary dataclass fields."""
        # Uses module-level imports to avoid cross-test pollution
        index_json = json.dumps({
            'moment_count': 3,
            'moment_ids': ['m1', 'm2', 'm3'],
            'journal_entry_ids': ['j1', 'j2', 'j3'],
        })
        row = {
            'id': 'ds-abc',
            'day_number': 42,
            'date': '2026-02-14',
            'journal_entry_id': None,
            'summary_bullets': index_json,
            'emotional_arc': 'conversation -> discovery',
            'notable_totems': json.dumps(['Nujabes', 'rain']),
            'created_at': '2026-02-14T03:30:00+00:00',
        }

        ds = _row_to_daily_summary(row)

        self.assertIsInstance(ds, DailySummary)
        self.assertEqual(ds.id, 'ds-abc')
        self.assertEqual(ds.day_number, 42)
        self.assertEqual(ds.date, '2026-02-14')
        self.assertEqual(ds.moment_count, 3)
        self.assertEqual(ds.moment_ids, ['m1', 'm2', 'm3'])
        self.assertEqual(ds.journal_entry_ids, ['j1', 'j2', 'j3'])
        self.assertEqual(ds.emotional_arc, 'conversation -> discovery')
        self.assertEqual(ds.notable_totems, ['Nujabes', 'rain'])
        self.assertIsNotNone(ds.created_at)

    def test_daily_summary_round_trip_empty_index(self):
        """_row_to_daily_summary handles NULL/empty summary_bullets gracefully."""
        # Uses module-level import to avoid cross-test pollution
        row = {
            'id': 'ds-empty',
            'day_number': 1,
            'date': '2026-02-14',
            'journal_entry_id': None,
            'summary_bullets': None,
            'emotional_arc': 'quiet',
            'notable_totems': None,
            'created_at': None,
        }

        ds = _row_to_daily_summary(row)
        self.assertEqual(ds.moment_count, 0)
        self.assertEqual(ds.moment_ids, [])
        self.assertEqual(ds.journal_entry_ids, [])
        self.assertEqual(ds.notable_totems, [])
