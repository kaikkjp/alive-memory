from contextlib import asynccontextmanager
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

from pipeline import cold_search
from pipeline import embed_cold


@asynccontextmanager
async def _noop_embed_session():
    yield


class ColdMemoryE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_embed_pipeline_then_search_excludes_today(self):
        now_utc = datetime.now(timezone.utc)
        old_ts = now_utc - timedelta(days=2)
        today_ts = now_utc
        store = []

        async def fake_get_unembedded_conversations(limit=50):
            self.assertEqual(limit, 50)
            return [
                {
                    "id": "old-msg",
                    "visitor_id": "v1",
                    "role": "visitor",
                    "text": "old memory",
                    "ts": old_ts.isoformat(),
                },
                {
                    "id": "today-msg",
                    "visitor_id": "v1",
                    "role": "shopkeeper",
                    "text": "today memory",
                    "ts": today_ts.isoformat(),
                },
            ]

        async def fake_get_unembedded_monologues(limit=50):
            self.assertEqual(limit, 50)
            return []

        async def fake_insert_cold_embedding(
            source_type,
            source_id,
            text_content,
            ts,
            embedding,
            embed_model,
        ):
            store.append(
                {
                    "source_type": source_type,
                    "source_id": source_id,
                    "text_content": text_content,
                    "ts_iso": ts.isoformat(),
                    "embed_model": embed_model,
                    "distance": 0.1 if source_id == "old-msg" else 0.2,
                }
            )

        async def fake_vector_search_cold_memory(query_embedding, limit=3, exclude_after_iso=None):
            _ = query_embedding
            rows = sorted(store, key=lambda x: x["distance"])
            out = []
            for row in rows:
                if exclude_after_iso and row["ts_iso"] >= exclude_after_iso:
                    continue
                out.append(row)
                if len(out) >= limit:
                    break
            return out

        async def fake_get_conversation_context(message_id, before=2, after=2):
            _ = before
            _ = after
            return [{"role": "visitor", "text": f"context for {message_id}"}]

        with patch.object(embed_cold.db, "get_unembedded_conversations", new=AsyncMock(side_effect=fake_get_unembedded_conversations)):
            with patch.object(embed_cold.db, "get_unembedded_monologues", new=AsyncMock(side_effect=fake_get_unembedded_monologues)):
                with patch.object(embed_cold.db, "insert_cold_embedding", new=AsyncMock(side_effect=fake_insert_cold_embedding)):
                    with patch.object(embed_cold, "embed_model_name", return_value="mock-model"):
                        with patch.object(embed_cold, "embed", new=AsyncMock(return_value=[0.1] * 1536)):
                            with patch.object(embed_cold, "embed_session", new=_noop_embed_session):
                                stats = await embed_cold.embed_new_cold_entries()

        self.assertEqual(stats["conversations_embedded"], 2)
        self.assertEqual(stats["monologues_embedded"], 0)
        self.assertEqual(stats["errors"], 0)

        with patch.object(cold_search, "embed", new=AsyncMock(return_value=[0.1] * 1536)):
            with patch.object(cold_search.db, "vector_search_cold_memory", new=AsyncMock(side_effect=fake_vector_search_cold_memory)):
                with patch.object(cold_search.db, "get_conversation_context", new=AsyncMock(side_effect=fake_get_conversation_context)):
                    with patch.object(cold_search.db, "get_cycle_by_id", new=AsyncMock(return_value=None)):
                        excluded = await cold_search.search_cold_memory(
                            query="memory",
                            limit=3,
                            exclude_today=True,
                        )
                        included = await cold_search.search_cold_memory(
                            query="memory",
                            limit=3,
                            exclude_today=False,
                        )

        self.assertEqual([r["summary"] for r in excluded], ["visitor: old memory"])
        self.assertEqual(len(included), 2)
        self.assertIn("context for old-msg", excluded[0]["context"])
