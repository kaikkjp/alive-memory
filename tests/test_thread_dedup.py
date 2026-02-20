"""Tests for HOTFIX-003: Thread deduplication.

Verifies that opening a thread with the same or similar topic merges into
the existing open thread rather than creating a duplicate.
"""

import types
import unittest
from unittest.mock import AsyncMock, patch

from tests.aiohttp_stub import ensure_aiohttp_stub
ensure_aiohttp_stub()

from pipeline.hippocampus_write import _find_duplicate_thread, hippocampus_consolidate


def _thread(id="t1", title="What is anti-pleasure?", status="open"):
    return types.SimpleNamespace(
        id=id,
        thread_type="question",
        title=title,
        status=status,
        priority=0.5,
        content="First thought",
        resolution=None,
        created_at=None,
        last_touched=None,
        touch_count=0,
        touch_reason=None,
        target_date=None,
        source_visitor_id=None,
        source_event_id=None,
        tags=[],
    )


class TestFindDuplicateThread(unittest.IsolatedAsyncioTestCase):
    """Tests for _find_duplicate_thread helper."""

    @patch('pipeline.hippocampus_write.db')
    async def test_exact_match(self, mock_db):
        """Exact same title (case-insensitive) finds the duplicate."""
        existing = _thread(id="t1", title="What is anti-pleasure?")
        mock_db.get_open_threads = AsyncMock(return_value=[existing])

        result = await _find_duplicate_thread("What is anti-pleasure?")
        assert result is not None
        assert result.id == "t1"

    @patch('pipeline.hippocampus_write.db')
    async def test_exact_match_case_insensitive(self, mock_db):
        """Case-insensitive exact match works."""
        existing = _thread(id="t1", title="What is anti-pleasure?")
        mock_db.get_open_threads = AsyncMock(return_value=[existing])

        result = await _find_duplicate_thread("WHAT IS ANTI-PLEASURE?")
        assert result is not None
        assert result.id == "t1"

    @patch('pipeline.hippocampus_write.db')
    async def test_fuzzy_match(self, mock_db):
        """Similar topics merge (>60% word overlap)."""
        existing = _thread(id="t1", title="What is anti-pleasure?")
        mock_db.get_open_threads = AsyncMock(return_value=[existing])

        result = await _find_duplicate_thread("anti-pleasure question")
        assert result is not None
        assert result.id == "t1"

    @patch('pipeline.hippocampus_write.db')
    async def test_different_topics_no_match(self, mock_db):
        """Genuinely different topics don't match."""
        existing = _thread(id="t1", title="What is anti-pleasure?")
        mock_db.get_open_threads = AsyncMock(return_value=[existing])

        result = await _find_duplicate_thread("Vintage Carddass pricing trends")
        assert result is None

    @patch('pipeline.hippocampus_write.db')
    async def test_no_open_threads(self, mock_db):
        """No open threads means no duplicate."""
        mock_db.get_open_threads = AsyncMock(return_value=[])

        result = await _find_duplicate_thread("anything")
        assert result is None


class TestThreadCreateDedup(unittest.IsolatedAsyncioTestCase):
    """Tests for thread_create dedup integration in hippocampus_consolidate."""

    @patch('pipeline.hippocampus_write.db')
    async def test_duplicate_merges(self, mock_db):
        """thread_create with duplicate title merges into existing."""
        existing = _thread(id="t1", title="What is anti-pleasure?")
        mock_db.get_open_threads = AsyncMock(return_value=[existing])
        mock_db.append_to_thread = AsyncMock()
        mock_db.create_thread = AsyncMock()

        await hippocampus_consolidate(
            {'type': 'thread_create', 'content': {
                'title': 'What is anti-pleasure?',
                'initial_thought': 'Second thought about this',
            }},
            visitor_id=None,
        )

        mock_db.append_to_thread.assert_called_once_with("t1", "Second thought about this")
        mock_db.create_thread.assert_not_called()

    @patch('pipeline.hippocampus_write.db')
    async def test_unique_creates(self, mock_db):
        """thread_create with unique title creates new thread."""
        mock_db.get_open_threads = AsyncMock(return_value=[])
        mock_db.create_thread = AsyncMock()
        mock_db.append_to_thread = AsyncMock()

        await hippocampus_consolidate(
            {'type': 'thread_create', 'content': {
                'title': 'Brand new topic',
                'initial_thought': 'Fresh thought',
                'thread_type': 'question',
            }},
            visitor_id=None,
        )

        mock_db.create_thread.assert_called_once()
        mock_db.append_to_thread.assert_not_called()


if __name__ == '__main__':
    unittest.main()
