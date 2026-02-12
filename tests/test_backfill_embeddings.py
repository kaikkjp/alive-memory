import importlib
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()


def _load_backfill_module():
    """Import backfill module with environment restored after import-time mutation."""
    module_name = "scripts.backfill_embeddings"
    original_env = os.environ.copy()
    sys.modules.pop(module_name, None)
    with patch.dict(os.environ, original_env, clear=True):
        module = importlib.import_module(module_name)
    return module


def _joined_print_output(print_mock) -> str:
    lines = []
    for call in print_mock.call_args_list:
        lines.append(" ".join(str(a) for a in call.args))
    return "\n".join(lines)


class BackfillEmbeddingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_reports_complete_when_zero_embeds_and_zero_errors(self):
        backfill = _load_backfill_module()
        stats_seq = [
            {"conversations_embedded": 0, "monologues_embedded": 0, "errors": 0},
        ]
        with patch.object(backfill.db, "init_db", new=AsyncMock()):
            with patch.object(backfill.db, "close_db", new=AsyncMock()):
                with patch.object(backfill.db, "get_cold_embedding_count", new=AsyncMock(return_value=0)):
                    with patch.object(backfill, "embed_new_cold_entries", new=AsyncMock(side_effect=stats_seq)):
                        with patch.object(backfill.asyncio, "sleep", new=AsyncMock()):
                            with patch("builtins.print") as print_mock:
                                await backfill.main()

        output = _joined_print_output(print_mock)
        self.assertIn("Complete — no more entries to embed.", output)

    async def test_main_reports_error_stop_when_zero_embeds_with_errors(self):
        backfill = _load_backfill_module()
        stats_seq = [
            {"conversations_embedded": 0, "monologues_embedded": 0, "errors": 2},
        ]
        with patch.object(backfill.db, "init_db", new=AsyncMock()):
            with patch.object(backfill.db, "close_db", new=AsyncMock()):
                with patch.object(backfill.db, "get_cold_embedding_count", new=AsyncMock(return_value=0)):
                    with patch.object(backfill, "embed_new_cold_entries", new=AsyncMock(side_effect=stats_seq)):
                        with patch.object(backfill.asyncio, "sleep", new=AsyncMock()):
                            with patch("builtins.print") as print_mock:
                                await backfill.main()

        output = _joined_print_output(print_mock)
        self.assertIn("Stopped — 2 errors in last batch", output)
        self.assertNotIn("Complete — no more entries to embed.", output)

    async def test_main_continues_after_successful_batch_then_exits(self):
        backfill = _load_backfill_module()
        stats_seq = [
            {"conversations_embedded": 1, "monologues_embedded": 0, "errors": 0},
            {"conversations_embedded": 0, "monologues_embedded": 0, "errors": 0},
        ]
        with patch.object(backfill.db, "init_db", new=AsyncMock()):
            with patch.object(backfill.db, "close_db", new=AsyncMock()):
                with patch.object(backfill.db, "get_cold_embedding_count", new=AsyncMock(return_value=1)):
                    with patch.object(backfill, "embed_new_cold_entries", new=AsyncMock(side_effect=stats_seq)) as embed_mock:
                        with patch.object(backfill.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
                            with patch("builtins.print"):
                                await backfill.main()

        self.assertEqual(embed_mock.await_count, 2)
        sleep_mock.assert_awaited_once_with(1)
