import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

from pipeline import cold_search as cold_search_mod
from pipeline import embed_cold as embed_cold_mod
import sleep


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class SleepColdMemoryTests(unittest.IsolatedAsyncioTestCase):
    def _moment(self):
        return types.SimpleNamespace(
            id="m1",
            retry_count=0,
            visitor_id="v1",
            summary="today summary",
            moment_type="conversation",
            tags=["music"],
            ts=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )

    async def _run_sleep_cycle_with_common_patches(self):
        patches = [
            patch.object(sleep.db, "get_engagement_state", new=AsyncMock(return_value=types.SimpleNamespace(status="none"))),
            patch.object(sleep.db, "get_unprocessed_day_memory", new=AsyncMock(return_value=[self._moment()])),
            patch.object(sleep, "gather_hot_context", new=AsyncMock(return_value={})),
            patch.object(sleep, "sleep_reflect", new=AsyncMock(return_value={"memory_updates": [], "reflection": "ok"})),
            patch.object(sleep, "write_daily_summary", new=AsyncMock()),
            patch.object(sleep, "review_trait_stability", new=AsyncMock()),
            patch.object(sleep, "manage_thread_lifecycle", new=AsyncMock()),
            patch.object(sleep, "cleanup_content_pool", new=AsyncMock()),
            patch.object(sleep, "reset_drives_for_morning", new=AsyncMock()),
            patch.object(sleep, "flush_day_memory", new=AsyncMock()),
            patch.object(sleep.db, "mark_day_memory_processed", new=AsyncMock()),
            patch.object(sleep.db, "increment_day_memory_retry", new=AsyncMock()),
            patch.object(sleep, "hippocampus_consolidate", new=AsyncMock()),
            patch.object(sleep.db, "transaction", new=lambda: _Tx()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with patch.object(sleep, "COLD_SEARCH_ENABLED", True):
            return await sleep.sleep_cycle()

    async def test_sleep_cycle_continues_when_cold_search_raises(self):
        with patch.object(cold_search_mod, "search_cold_memory", new=AsyncMock(side_effect=RuntimeError("boom"))):
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
