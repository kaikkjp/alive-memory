from contextlib import asynccontextmanager
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

from pipeline import embed_cold


@asynccontextmanager
async def _noop_embed_session():
    yield


class EmbedColdTests(unittest.IsolatedAsyncioTestCase):
    async def test_embed_new_cold_entries_uses_batch_limit_and_embeds_rows(self):
        convos = [
            {
                "id": "c1",
                "role": "visitor",
                "text": "hello",
                "ts": "2026-02-10T00:00:00+00:00",
            }
        ]
        monos = [
            {
                "id": "m1",
                "internal_monologue": "this is a long monologue",
                "dialogue": "dialogue line",
                "ts": "2026-02-10T00:01:00+00:00",
            }
        ]

        with patch.object(embed_cold.db, "get_unembedded_conversations", new=AsyncMock(return_value=convos)) as get_convos:
            with patch.object(embed_cold.db, "get_unembedded_monologues", new=AsyncMock(return_value=monos)) as get_monos:
                with patch.object(embed_cold, "embed_model_name", return_value="mock-model"):
                    with patch.object(embed_cold, "embed", new=AsyncMock(return_value=[0.1] * 1536)):
                        with patch.object(embed_cold.db, "insert_cold_embedding", new=AsyncMock()) as insert_mock:
                            with patch.object(embed_cold, "embed_session", new=_noop_embed_session):
                                stats = await embed_cold.embed_new_cold_entries()

        self.assertEqual(stats["conversations_embedded"], 1)
        self.assertEqual(stats["monologues_embedded"], 1)
        self.assertEqual(stats["errors"], 0)
        get_convos.assert_awaited_once_with(limit=50)
        get_monos.assert_awaited_once_with(limit=50)
        self.assertEqual(insert_mock.await_count, 2)

    async def test_embed_new_cold_entries_counts_errors_but_continues(self):
        convos = [
            {
                "id": "c_none",
                "role": "visitor",
                "text": "none",
                "ts": "2026-02-10T00:00:00+00:00",
            },
            {
                "id": "c_raise",
                "role": "shopkeeper",
                "text": "raise",
                "ts": "2026-02-10T00:01:00+00:00",
            },
            {
                "id": "c_ok",
                "role": "visitor",
                "text": "ok",
                "ts": "2026-02-10T00:02:00+00:00",
            },
        ]
        monos = [
            {
                "id": "m_ok",
                "internal_monologue": "this monologue is definitely long enough",
                "dialogue": "",
                "ts": "2026-02-10T00:03:00+00:00",
            }
        ]

        async def fake_embed(text):
            if "none" in text:
                return None
            if "raise" in text:
                raise RuntimeError("embed fail")
            return [0.2] * 1536

        with patch.object(embed_cold.db, "get_unembedded_conversations", new=AsyncMock(return_value=convos)):
            with patch.object(embed_cold.db, "get_unembedded_monologues", new=AsyncMock(return_value=monos)):
                with patch.object(embed_cold, "embed_model_name", return_value="mock-model"):
                    with patch.object(embed_cold, "embed", new=AsyncMock(side_effect=fake_embed)):
                        with patch.object(embed_cold.db, "insert_cold_embedding", new=AsyncMock()) as insert_mock:
                            with patch.object(embed_cold, "embed_session", new=_noop_embed_session):
                                stats = await embed_cold.embed_new_cold_entries()

        self.assertEqual(stats["conversations_embedded"], 1)
        self.assertEqual(stats["monologues_embedded"], 1)
        self.assertEqual(stats["errors"], 2)
        self.assertEqual(insert_mock.await_count, 2)

    async def test_embed_new_cold_entries_passes_expected_insert_payload(self):
        convos = [
            {
                "id": "c1",
                "role": "shopkeeper",
                "text": "hey there",
                "ts": "2026-02-10T00:00:00+00:00",
            }
        ]
        monos = []

        with patch.object(embed_cold.db, "get_unembedded_conversations", new=AsyncMock(return_value=convos)):
            with patch.object(embed_cold.db, "get_unembedded_monologues", new=AsyncMock(return_value=monos)):
                with patch.object(embed_cold, "embed_model_name", return_value="embed-model-1"):
                    with patch.object(embed_cold, "embed", new=AsyncMock(return_value=[0.3] * 1536)):
                        with patch.object(embed_cold.db, "insert_cold_embedding", new=AsyncMock()) as insert_mock:
                            with patch.object(embed_cold, "embed_session", new=_noop_embed_session):
                                await embed_cold.embed_new_cold_entries()

        insert_mock.assert_awaited_once()
        kwargs = insert_mock.await_args.kwargs
        self.assertEqual(kwargs["source_type"], "conversation")
        self.assertEqual(kwargs["source_id"], "c1")
        self.assertEqual(kwargs["text_content"], "shopkeeper: hey there")
        self.assertEqual(kwargs["embed_model"], "embed-model-1")
        self.assertIsInstance(kwargs["ts"], datetime)
        self.assertEqual(kwargs["ts"].tzinfo, timezone.utc)
