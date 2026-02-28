"""Tests for TASK-095 v2: Cold memory origin tracking.

Verifies:
- Organic memory default origin
- Manager-injected memory origin
- Delete only manager memories
- Origin filtering
- Vector search includes origin
"""

import sys
import types
import unittest
from unittest.mock import AsyncMock, patch, MagicMock, PropertyMock
from datetime import datetime, timezone

# Stub sqlite_vec — always install our stub to ensure consistent behavior
# regardless of what previous test modules may have done to sys.modules
_sv_stub = types.ModuleType('sqlite_vec')
_sv_stub.serialize_float32 = lambda v: b'\x00' * (len(v) * 4)
sys.modules['sqlite_vec'] = _sv_stub


class TestInsertColdEmbeddingOrigin(unittest.IsolatedAsyncioTestCase):
    """Test that insert_cold_embedding writes to cold_memory_origin."""

    @patch('db.memory._connection')
    @patch('db.memory._write_lock')
    async def test_organic_memory_default_origin(self, mock_lock, mock_conn):
        """Normal cold memory write should have origin='organic' by default."""
        import db.memory as mem

        # Mock the async context manager for _write_lock
        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        # Dedupe check returns None (not already embedded)
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()

        import sqlite_vec
        with patch('db.memory.sqlite_vec', create=True) as mock_sv:
            mock_sv.serialize_float32 = MagicMock(return_value=b'\x00' * 6144)

            await mem.insert_cold_embedding(
                source_type='conversation',
                source_id='test-123',
                text_content='Hello world',
                ts=datetime.now(timezone.utc),
                embedding=[0.0] * 1536,
                embed_model='test',
            )

        # Should have called execute 3 times:
        # 1. Dedupe check, 2. vec insert, 3. origin insert
        calls = mock_db.execute.call_args_list
        self.assertEqual(len(calls), 3)
        # Third call should be the origin insert
        origin_sql = calls[2][0][0]
        self.assertIn('cold_memory_origin', origin_sql)
        origin_args = calls[2][0][1]
        self.assertEqual(origin_args, ('test-123', 'organic'))

    @patch('db.memory._connection')
    @patch('db.memory._write_lock')
    async def test_inject_manager_memory_stores_origin(self, mock_lock, mock_conn):
        """Manager-injected memories should have origin='manager_injected'."""
        import db.memory as mem

        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()

        import sqlite_vec
        with patch('db.memory.sqlite_vec', create=True) as mock_sv:
            mock_sv.serialize_float32 = MagicMock(return_value=b'\x00' * 6144)
            with patch('db.memory.clock') as mock_clock:
                mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

                source_id = await mem.inject_manager_memory(
                    text='She loved the rain.',
                    title='Early memory',
                )

        self.assertTrue(source_id.startswith('mgr-'))

        # Check that origin insert used 'manager_injected'
        execute_calls = mock_db.execute.call_args_list
        origin_calls = [c for c in execute_calls
                       if 'cold_memory_origin' in str(c)]
        self.assertTrue(len(origin_calls) > 0)
        # At least one call should have 'manager_injected'
        found_manager = any('manager_injected' in str(c) for c in origin_calls)
        self.assertTrue(found_manager)


class TestDeleteManagerMemory(unittest.IsolatedAsyncioTestCase):
    @patch('db.memory._connection')
    @patch('db.memory._write_lock')
    async def test_delete_manager_memory_allowed(self, mock_lock, mock_conn):
        """Should allow deleting manager-injected memories."""
        import db.memory as mem

        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        # First call: origin check → returns manager_injected
        mock_cursor_origin = AsyncMock()
        mock_cursor_origin.fetchone = AsyncMock(return_value={'origin': 'manager_injected'})

        # Subsequent calls: deletes
        mock_db.execute = AsyncMock(return_value=mock_cursor_origin)
        mock_db.commit = AsyncMock()

        result = await mem.delete_manager_memory('mgr-abc123')
        self.assertTrue(result)

    @patch('db.memory._connection')
    async def test_delete_organic_memory_blocked(self, mock_conn):
        """Should refuse to delete organic memories."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        # Origin check → returns organic
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={'origin': 'organic'})
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await mem.delete_manager_memory('conv-abc123')
        self.assertFalse(result)

    @patch('db.memory._connection')
    async def test_delete_nonexistent_memory(self, mock_conn):
        """Should return False for non-existent source_id."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await mem.delete_manager_memory('nonexistent')
        self.assertFalse(result)


class TestVectorSearchIncludesOrigin(unittest.IsolatedAsyncioTestCase):
    @patch('db.memory._connection')
    async def test_vector_search_includes_origin(self, mock_conn):
        """Search results should include origin field."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        # First call: vec search
        vec_row = {
            'source_type': 'conversation',
            'source_id': 'conv-1',
            'text_content': 'Hello',
            'ts_iso': '2026-01-01T00:00:00',
            'embed_model': 'test',
            'distance': 0.1,
        }
        mock_cursor_vec = AsyncMock()
        mock_cursor_vec.fetchall = AsyncMock(return_value=[vec_row])

        # Second call: origin lookup
        origin_row = {'source_id': 'conv-1', 'origin': 'organic'}
        mock_cursor_origin = AsyncMock()
        mock_cursor_origin.fetchall = AsyncMock(return_value=[origin_row])

        mock_db.execute = AsyncMock(side_effect=[mock_cursor_vec, mock_cursor_origin])

        import sqlite_vec
        with patch('db.memory.sqlite_vec', create=True) as mock_sv:
            mock_sv.serialize_float32 = MagicMock(return_value=b'\x00' * 6144)

            results = await mem.vector_search_cold_memory(
                query_embedding=[0.0] * 1536,
                limit=3,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['origin'], 'organic')

    @patch('db.memory._connection')
    async def test_vector_search_defaults_organic_if_no_origin_row(self, mock_conn):
        """Pre-existing memories without origin row should default to 'organic'."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        vec_row = {
            'source_type': 'conversation',
            'source_id': 'old-conv-1',
            'text_content': 'Old memory',
            'ts_iso': '2025-01-01T00:00:00',
            'embed_model': 'test',
            'distance': 0.2,
        }
        mock_cursor_vec = AsyncMock()
        mock_cursor_vec.fetchall = AsyncMock(return_value=[vec_row])

        # Origin lookup returns empty (no row for this memory)
        mock_cursor_origin = AsyncMock()
        mock_cursor_origin.fetchall = AsyncMock(return_value=[])

        mock_db.execute = AsyncMock(side_effect=[mock_cursor_vec, mock_cursor_origin])

        import sqlite_vec
        with patch('db.memory.sqlite_vec', create=True) as mock_sv:
            mock_sv.serialize_float32 = MagicMock(return_value=b'\x00' * 6144)

            results = await mem.vector_search_cold_memory(
                query_embedding=[0.0] * 1536,
                limit=3,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['origin'], 'organic')


class TestGetMemoriesByOrigin(unittest.IsolatedAsyncioTestCase):
    @patch('db.memory._connection')
    async def test_get_organic_memories(self, mock_conn):
        """Should filter by origin='organic'."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        rows = [
            {'source_type': 'conversation', 'source_id': 'c1',
             'text_content': 'Hi', 'ts_iso': '2026-01-01', 'origin': 'organic'},
        ]
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await mem.get_organic_memories(limit=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['origin'], 'organic')

        # Verify query filters by origin (uses COALESCE for LEFT JOIN)
        sql = mock_db.execute.call_args[0][0]
        self.assertIn("COALESCE(o.origin, 'organic') = ?", sql)
        params = mock_db.execute.call_args[0][1]
        self.assertEqual(params[0], 'organic')

    @patch('db.memory._connection')
    async def test_get_manager_memories(self, mock_conn):
        """Should return all manager-injected memories."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        rows = [
            {'source_type': 'manager_backstory', 'source_id': 'mgr-1',
             'text_content': 'Rain story', 'ts_iso': '2026-01-01',
             'origin': 'manager_injected'},
        ]
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await mem.get_manager_memories()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['origin'], 'manager_injected')


class TestFallbackWithoutColdMemoryVec(unittest.IsolatedAsyncioTestCase):
    """Tests for agents without COLD_SEARCH_ENABLED (no cold_memory_vec table)."""

    @patch('db.memory._connection')
    async def test_get_manager_memories_falls_back_to_manager_memories_table(self, mock_conn):
        """When cold_memory_vec query fails, should fall back to manager_memories."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        mm_rows = [
            {'source_type': 'manager_backstory', 'source_id': 'mgr-1',
             'text_content': 'Tokyo alley', 'ts_iso': '2026-02-01T00:00:00',
             'origin': 'manager_injected'},
        ]
        mm_cursor = AsyncMock()
        mm_cursor.fetchall = AsyncMock(return_value=mm_rows)

        # First execute (cold_memory_vec) raises, second (manager_memories) succeeds
        mock_db.execute = AsyncMock(
            side_effect=[Exception('no such table: cold_memory_vec'), mm_cursor]
        )

        result = await mem.get_manager_memories()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['source_id'], 'mgr-1')
        self.assertEqual(result[0]['text_content'], 'Tokyo alley')

    @patch('db.memory._connection')
    async def test_get_organic_memories_returns_empty_when_vec_missing(self, mock_conn):
        """Organic memories query should return [] when cold_memory_vec is missing."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        mock_db.execute = AsyncMock(
            side_effect=Exception('no such table: cold_memory_vec')
        )

        result = await mem.get_organic_memories(limit=10)
        self.assertEqual(result, [])

    @patch('db.memory._connection')
    async def test_manager_memories_merges_and_deduplicates(self, mock_conn):
        """When both sources have rows, should merge, dedupe, sort by ts_iso desc."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        vec_rows = [
            {'source_type': 'manager_backstory', 'source_id': 'mgr-dup',
             'text_content': 'Old version', 'ts_iso': '2026-01-01T00:00:00',
             'origin': 'manager_injected'},
            {'source_type': 'manager_backstory', 'source_id': 'mgr-vec-only',
             'text_content': 'Vec only', 'ts_iso': '2026-01-02T00:00:00',
             'origin': 'manager_injected'},
        ]
        mm_rows = [
            {'source_type': 'manager_backstory', 'source_id': 'mgr-dup',
             'text_content': 'New version', 'ts_iso': '2026-02-01T00:00:00',
             'origin': 'manager_injected'},
            {'source_type': 'manager_backstory', 'source_id': 'mgr-mm-only',
             'text_content': 'MM only', 'ts_iso': '2026-01-15T00:00:00',
             'origin': 'manager_injected'},
        ]

        vec_cursor = AsyncMock()
        vec_cursor.fetchall = AsyncMock(return_value=vec_rows)
        mm_cursor = AsyncMock()
        mm_cursor.fetchall = AsyncMock(return_value=mm_rows)

        mock_db.execute = AsyncMock(side_effect=[vec_cursor, mm_cursor])

        result = await mem.get_cold_memories_by_origin('manager_injected', limit=50)

        # Should have 3 unique entries (mgr-dup deduplicated)
        self.assertEqual(len(result), 3)
        ids = [r['source_id'] for r in result]
        self.assertIn('mgr-dup', ids)
        self.assertIn('mgr-vec-only', ids)
        self.assertIn('mgr-mm-only', ids)

        # Newest first
        self.assertEqual(result[0]['source_id'], 'mgr-dup')
        self.assertEqual(result[0]['ts_iso'], '2026-02-01T00:00:00')

    @patch('db.memory._connection')
    async def test_pagination_applied_globally_after_merge(self, mock_conn):
        """offset+limit should be applied after merge, not per-source."""
        import db.memory as mem

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        # 3 items total across sources (no overlap)
        vec_rows = [
            {'source_type': 'manager_backstory', 'source_id': 'mgr-a',
             'text_content': 'A', 'ts_iso': '2026-03-01T00:00:00',
             'origin': 'manager_injected'},
        ]
        mm_rows = [
            {'source_type': 'manager_backstory', 'source_id': 'mgr-b',
             'text_content': 'B', 'ts_iso': '2026-02-01T00:00:00',
             'origin': 'manager_injected'},
            {'source_type': 'manager_backstory', 'source_id': 'mgr-c',
             'text_content': 'C', 'ts_iso': '2026-01-01T00:00:00',
             'origin': 'manager_injected'},
        ]

        vec_cursor = AsyncMock()
        vec_cursor.fetchall = AsyncMock(return_value=vec_rows)
        mm_cursor = AsyncMock()
        mm_cursor.fetchall = AsyncMock(return_value=mm_rows)

        mock_db.execute = AsyncMock(side_effect=[vec_cursor, mm_cursor])

        # Page 2: offset=1, limit=1 should return mgr-b (second by date)
        result = await mem.get_cold_memories_by_origin(
            'manager_injected', limit=1, offset=1
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['source_id'], 'mgr-b')

    @patch('db.memory._connection')
    @patch('db.memory._write_lock')
    async def test_inject_without_embedding_uses_manager_memories_table(self, mock_lock, mock_conn):
        """inject_manager_memory without embedding should write to manager_memories."""
        import db.memory as mem

        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)
        mock_db.execute = AsyncMock(return_value=AsyncMock())
        mock_db.commit = AsyncMock()

        with patch('db.memory.clock') as mock_clock:
            mock_clock.now_utc.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            source_id = await mem.inject_manager_memory(
                text='Rain on the alley',
                title='First rain',
            )

        self.assertTrue(source_id.startswith('mgr-'))

        # Should write to manager_memories, not cold_memory_vec
        execute_calls = mock_db.execute.call_args_list
        sql_stmts = [str(c[0][0]) for c in execute_calls]
        self.assertTrue(any('manager_memories' in s for s in sql_stmts),
                        f"Expected manager_memories INSERT, got: {sql_stmts}")
        self.assertFalse(any('cold_memory_vec' in s for s in sql_stmts),
                         "Should not touch cold_memory_vec without embedding")

    @patch('db.memory._connection')
    @patch('db.memory._write_lock')
    async def test_delete_succeeds_when_vec_table_missing(self, mock_lock, mock_conn):
        """delete_manager_memory should succeed even without cold_memory_vec."""
        import db.memory as mem

        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_conn.get_db = AsyncMock(return_value=mock_db)

        # Origin check succeeds
        origin_cursor = AsyncMock()
        origin_cursor.fetchone = AsyncMock(return_value={'origin': 'manager_injected'})

        call_count = 0
        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Origin check
                return origin_cursor
            if 'cold_memory_vec' in sql:
                raise Exception('no such table: cold_memory_vec')
            return AsyncMock()

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        mock_db.commit = AsyncMock()

        result = await mem.delete_manager_memory('mgr-abc123')
        self.assertTrue(result)
        # Should have attempted all deletes despite vec failure
        self.assertGreaterEqual(call_count, 3)


if __name__ == '__main__':
    unittest.main()
