import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import aiosqlite

import db


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.last_params = None

    async def execute(self, _sql, params=()):
        self.last_params = params
        return _FakeCursor(self._rows)


class DBColdMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if db._db is not None:
            try:
                await db._db.close()
            except Exception:
                pass
        db._db = None

    async def test_get_db_does_not_crash_when_extension_loading_unsupported(self):
        fake_conn = types.SimpleNamespace()
        fake_conn.row_factory = None
        fake_conn.execute = AsyncMock()
        fake_conn.close = AsyncMock()
        fake_conn.enable_load_extension = AsyncMock(
            side_effect=AttributeError("no extension support")
        )

        sqlite_vec_stub = types.SimpleNamespace(load=lambda _conn: None)
        with patch.dict(sys.modules, {"sqlite_vec": sqlite_vec_stub}):
            with patch.object(db, "COLD_SEARCH_ENABLED", True):
                with patch.object(db.aiosqlite, "connect", new=AsyncMock(return_value=fake_conn)):
                    conn = await db.get_db()

        self.assertIs(conn, fake_conn)
        pragma_calls = [c.args[0] for c in fake_conn.execute.call_args_list]
        self.assertIn("PRAGMA journal_mode=WAL", pragma_calls)
        self.assertIn("PRAGMA busy_timeout=5000", pragma_calls)
        self.assertIn("PRAGMA foreign_keys=ON", pragma_calls)
        self.assertEqual(fake_conn.enable_load_extension.call_count, 1)

    async def test_get_unembedded_conversations_filters_roles_and_embedded_rows(self):
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "CREATE TABLE conversation_log (id TEXT, visitor_id TEXT, role TEXT, text TEXT, ts TEXT)"
        )
        await conn.execute(
            "CREATE TABLE cold_memory_vec (source_type TEXT, source_id TEXT)"
        )
        await conn.executemany(
            "INSERT INTO conversation_log (id, visitor_id, role, text, ts) VALUES (?, ?, ?, ?, ?)",
            [
                ("m1", "v1", "visitor", "hello", "2026-02-10T00:00:00+00:00"),
                ("m2", "v1", "shopkeeper", "hi", "2026-02-10T00:01:00+00:00"),
                ("m3", "v1", "system", "__session_boundary__", "2026-02-10T00:02:00+00:00"),
            ],
        )
        await conn.execute(
            "INSERT INTO cold_memory_vec (source_type, source_id) VALUES ('conversation', 'm1')"
        )
        await conn.commit()

        with patch.object(db, "get_db", new=AsyncMock(return_value=conn)):
            rows = await db.get_unembedded_conversations(limit=10)

        self.assertEqual([r["id"] for r in rows], ["m2"])
        await conn.close()

    async def test_get_unembedded_monologues_skips_short_and_already_embedded(self):
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "CREATE TABLE cycle_log (id TEXT, internal_monologue TEXT, dialogue TEXT, ts TEXT)"
        )
        await conn.execute(
            "CREATE TABLE cold_memory_vec (source_type TEXT, source_id TEXT)"
        )
        await conn.executemany(
            "INSERT INTO cycle_log (id, internal_monologue, dialogue, ts) VALUES (?, ?, ?, ?)",
            [
                ("c1", "short", "", "2026-02-10T00:00:00+00:00"),
                ("c2", "this is long enough", "", "2026-02-10T00:01:00+00:00"),
                ("c3", "another long enough monologue", "", "2026-02-10T00:02:00+00:00"),
            ],
        )
        await conn.execute(
            "INSERT INTO cold_memory_vec (source_type, source_id) VALUES ('monologue', 'c2')"
        )
        await conn.commit()

        with patch.object(db, "get_db", new=AsyncMock(return_value=conn)):
            rows = await db.get_unembedded_monologues(limit=10)

        self.assertEqual([r["id"] for r in rows], ["c3"])
        await conn.close()

    async def test_insert_cold_embedding_dedupes_and_truncates_text(self):
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "CREATE TABLE cold_memory_vec (embedding BLOB, source_type TEXT, source_id TEXT, "
            "text_content TEXT, ts_iso TEXT, embed_model TEXT)"
        )
        await conn.commit()

        sqlite_vec_stub = types.SimpleNamespace(serialize_float32=lambda _x: b"vec")
        long_text = "x" * 900

        with patch.dict(sys.modules, {"sqlite_vec": sqlite_vec_stub}):
            with patch.object(db, "get_db", new=AsyncMock(return_value=conn)):
                await db.insert_cold_embedding(
                    source_type="conversation",
                    source_id="mid-1",
                    text_content=long_text,
                    ts=datetime(2026, 2, 10, tzinfo=timezone.utc),
                    embedding=[0.1, 0.2],
                    embed_model="model",
                )
                await db.insert_cold_embedding(
                    source_type="conversation",
                    source_id="mid-1",
                    text_content="different",
                    ts=datetime(2026, 2, 10, tzinfo=timezone.utc),
                    embedding=[0.1, 0.2],
                    embed_model="model",
                )

        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt, MAX(LENGTH(text_content)) as max_len FROM cold_memory_vec"
        )
        row = await cursor.fetchone()
        self.assertEqual(row["cnt"], 1)
        self.assertEqual(row["max_len"], 500)
        await conn.close()

    async def test_vector_search_filters_excluded_timestamps_and_limits_results(self):
        rows = [
            {
                "source_type": "conversation",
                "source_id": "old-1",
                "text_content": "a",
                "ts_iso": "2026-02-09T00:00:00+00:00",
                "embed_model": "m",
                "distance": 0.1,
            },
            {
                "source_type": "conversation",
                "source_id": "new-1",
                "text_content": "b",
                "ts_iso": "2026-02-12T12:00:00+00:00",
                "embed_model": "m",
                "distance": 0.2,
            },
            {
                "source_type": "monologue",
                "source_id": "old-2",
                "text_content": "c",
                "ts_iso": "2026-02-08T00:00:00+00:00",
                "embed_model": "m",
                "distance": 0.3,
            },
        ]
        fake_conn = _FakeConn(rows)
        sqlite_vec_stub = types.SimpleNamespace(serialize_float32=lambda _x: b"qvec")

        with patch.dict(sys.modules, {"sqlite_vec": sqlite_vec_stub}):
            with patch.object(db, "get_db", new=AsyncMock(return_value=fake_conn)):
                out = await db.vector_search_cold_memory(
                    query_embedding=[0.1, 0.2],
                    limit=2,
                    exclude_after_iso="2026-02-12T00:00:00+00:00",
                )

        self.assertEqual([r["source_id"] for r in out], ["old-1", "old-2"])
        self.assertEqual(fake_conn.last_params[1], 6)  # limit * 3 when exclusion is enabled

    async def test_get_conversation_context_returns_ordered_window(self):
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "CREATE TABLE conversation_log (id TEXT, visitor_id TEXT, role TEXT, text TEXT, ts TEXT)"
        )
        base = datetime(2026, 2, 10, tzinfo=timezone.utc)
        rows = [
            ("a", "v1", "visitor", "one", (base + timedelta(seconds=1)).isoformat()),
            ("b", "v1", "shopkeeper", "two", (base + timedelta(seconds=2)).isoformat()),
            ("c", "v1", "visitor", "target", (base + timedelta(seconds=3)).isoformat()),
            ("d", "v1", "shopkeeper", "four", (base + timedelta(seconds=4)).isoformat()),
            ("e", "v1", "visitor", "five", (base + timedelta(seconds=5)).isoformat()),
        ]
        await conn.executemany(
            "INSERT INTO conversation_log (id, visitor_id, role, text, ts) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        await conn.commit()

        with patch.object(db, "get_db", new=AsyncMock(return_value=conn)):
            context = await db.get_conversation_context("c", before=2, after=1)

        self.assertEqual([m["text"] for m in context], ["one", "two", "target", "four"])
        await conn.close()
