"""Tests for /api/dashboard/feed endpoint (TASK-027).

Verifies that the feed pipeline dashboard handler returns the correct
JSON shape and enforces authentication, and that the DB query function
returns correct data.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db
from api.dashboard_routes import (
    _create_dashboard_token,
    _dashboard_tokens,
    handle_feed,
)


def _make_server():
    """Create a mock server with _http_json."""
    server = MagicMock()
    server._http_json = AsyncMock()
    return server


def _run(coro):
    """Run an async coroutine."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestFeedRouteAuth(unittest.TestCase):
    """Test that /api/dashboard/feed rejects unauthenticated requests."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def test_feed_unauthorized(self):
        server = _make_server()
        writer = MagicMock()
        _run(handle_feed(server, writer, ''))
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 401)


class TestFeedRouteShape(unittest.TestCase):
    """Test that /api/dashboard/feed returns correct JSON shape."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    @patch('api.dashboard_routes.db')
    def test_feed_authorized_returns_shape(self, mock_db):
        mock_db.get_feed_pipeline_dashboard = AsyncMock(return_value={
            'status': 'running',
            'queue_depth': 15,
            'last_success_ts': '2026-02-16T01:00:00+00:00',
            'failed_24h': 0,
            'last_error': None,
            'rate_24h': 42,
        })
        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'
        _run(handle_feed(server, writer, auth))
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)
        data = args[0][2]
        self.assertEqual(data['status'], 'running')
        self.assertEqual(data['queue_depth'], 15)
        self.assertEqual(data['last_success_ts'], '2026-02-16T01:00:00+00:00')
        self.assertEqual(data['failed_24h'], 0)
        self.assertIsNone(data['last_error'])
        self.assertEqual(data['rate_24h'], 42)

    @patch('api.dashboard_routes.db')
    def test_feed_empty_pool(self, mock_db):
        mock_db.get_feed_pipeline_dashboard = AsyncMock(return_value={
            'status': 'paused',
            'queue_depth': 0,
            'last_success_ts': None,
            'failed_24h': 0,
            'last_error': None,
            'rate_24h': 0,
        })
        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'
        _run(handle_feed(server, writer, auth))
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)
        data = args[0][2]
        self.assertEqual(data['status'], 'paused')
        self.assertEqual(data['queue_depth'], 0)
        self.assertIsNone(data['last_success_ts'])
        self.assertEqual(data['rate_24h'], 0)

    @patch('api.dashboard_routes.db')
    def test_feed_error_state_with_message(self, mock_db):
        mock_db.get_feed_pipeline_dashboard = AsyncMock(return_value={
            'status': 'error',
            'queue_depth': 5,
            'last_success_ts': '2026-02-15T23:00:00+00:00',
            'failed_24h': 3,
            'last_error': 'RSS parse error: malformed XML',
            'rate_24h': 10,
        })
        server = _make_server()
        writer = MagicMock()
        token = _create_dashboard_token()
        auth = f'Bearer {token}'
        _run(handle_feed(server, writer, auth))
        args = server._http_json.call_args
        self.assertEqual(args[0][1], 200)
        data = args[0][2]
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['failed_24h'], 3)
        self.assertEqual(data['last_error'], 'RSS parse error: malformed XML')


# ─── DB-level tests using pytest fixtures ───

@pytest.fixture(autouse=False)
async def fresh_db(tmp_path):
    """Use a temp database for each test, with singleton rows seeded."""
    db._db = None
    original_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "test.db")
    await db.init_db()
    yield
    await db.close_db()
    db.DB_PATH = original_path


class TestFeedPipelineDashboardQuery:
    """Test the db.get_feed_pipeline_dashboard() query function directly."""

    @pytest.mark.asyncio
    async def test_returns_all_required_keys(self, fresh_db):
        """Verify the function returns all required keys for the panel."""
        result = await db.get_feed_pipeline_dashboard()
        assert 'status' in result
        assert 'queue_depth' in result
        assert 'last_success_ts' in result
        assert 'failed_24h' in result
        assert 'last_error' in result
        assert 'rate_24h' in result
        assert result['status'] in ('running', 'paused', 'error')
        assert isinstance(result['queue_depth'], int)
        assert isinstance(result['failed_24h'], int)
        assert isinstance(result['rate_24h'], int)

    @pytest.mark.asyncio
    async def test_empty_pool_returns_paused(self, fresh_db):
        """Empty content pool → paused status."""
        result = await db.get_feed_pipeline_dashboard()
        assert result['status'] == 'paused'
        assert result['queue_depth'] == 0
        assert result['last_success_ts'] is None
        assert result['failed_24h'] == 0
        assert result['last_error'] is None
        assert result['rate_24h'] == 0

    @pytest.mark.asyncio
    async def test_with_recent_items_returns_running(self, fresh_db):
        """Recent ingestion activity → running status."""
        await db.add_to_content_pool(
            fingerprint='test-fp-1',
            source_type='rss_headline',
            source_channel='rss',
            content='https://example.com/article',
            title='Test article',
        )
        result = await db.get_feed_pipeline_dashboard()
        assert result['status'] == 'running'
        assert result['queue_depth'] == 1
        assert result['last_success_ts'] is not None
        assert result['rate_24h'] == 1


if __name__ == '__main__':
    unittest.main()
