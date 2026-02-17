"""Tests for pipeline/notifications.py — notification surfacing layer.

TASK-041: Verifies notification surfacing, cooldown enforcement,
saved item priority, source diversity, and empty pool handling.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.notifications import (
    get_notifications,
    format_notifications_text,
    Notification,
    NOTIFICATION_CONFIG,
)


def _make_pool_item(id='item-1', title='Test Article', source_channel='rss_feed',
                    content_type='article', source_type='rss_headline',
                    saved_by_cortex=False, saved_at=None, **kwargs):
    """Create a mock content pool item dict."""
    return {
        'id': id,
        'title': title,
        'source_channel': source_channel,
        'content_type': content_type,
        'source_type': source_type,
        'status': 'unseen',
        'saved_by_cortex': saved_by_cortex,
        'saved_at': saved_at,
        'content': f'https://example.com/{id}',
        'enriched_text': None,
        **kwargs,
    }


@pytest.fixture(autouse=True)
def _patch_notification_deps():
    """Patch db and clock at the pipeline.notifications module level."""
    mock_db = MagicMock()
    mock_db.get_notification_candidates = AsyncMock(return_value=[])
    mock_db.log_notification_surfaced = AsyncMock(return_value=None)
    mock_db.expire_saved_items = AsyncMock(return_value=None)

    mock_clock = MagicMock()
    mock_clock.now_utc = MagicMock(
        return_value=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    )

    with patch('pipeline.notifications.db', mock_db), \
         patch('pipeline.notifications.clock', mock_clock):
        yield mock_db, mock_clock


@pytest.fixture
def mock_db(_patch_notification_deps):
    return _patch_notification_deps[0]


@pytest.fixture
def mock_clock(_patch_notification_deps):
    return _patch_notification_deps[1]


class TestGetNotifications:
    """get_notifications() surfaces content titles from the pool."""

    @pytest.mark.asyncio
    async def test_get_notifications_returns_n_items(self, mock_db):
        """Returns up to max_per_cycle items."""
        items = [_make_pool_item(id=f'item-{i}', title=f'Article {i}')
                 for i in range(5)]
        mock_db.get_notification_candidates = AsyncMock(return_value=items)

        notifications = await get_notifications()

        assert len(notifications) == 5
        assert all(isinstance(n, Notification) for n in notifications)
        assert notifications[0].title == 'Article 0'
        assert notifications[0].content_id == 'item-0'

    @pytest.mark.asyncio
    async def test_empty_pool_returns_empty(self, mock_db):
        """No crash on empty content_pool."""
        mock_db.get_notification_candidates = AsyncMock(return_value=[])

        notifications = await get_notifications()

        assert notifications == []

    @pytest.mark.asyncio
    async def test_cooldown_enforced(self, mock_db):
        """Cooldown minutes are passed to get_notification_candidates."""
        mock_db.get_notification_candidates = AsyncMock(return_value=[])

        await get_notifications()

        mock_db.get_notification_candidates.assert_called_once_with(
            max_items=NOTIFICATION_CONFIG['max_per_cycle'],
            cooldown_minutes=NOTIFICATION_CONFIG['cooldown_minutes'],
        )

    @pytest.mark.asyncio
    async def test_notifications_logged(self, mock_db):
        """Each surfaced notification is logged in notification_log."""
        items = [_make_pool_item(id='item-1'), _make_pool_item(id='item-2')]
        mock_db.get_notification_candidates = AsyncMock(return_value=items)

        await get_notifications(cycle_id='cycle-99')

        assert mock_db.log_notification_surfaced.call_count == 2
        calls = mock_db.log_notification_surfaced.call_args_list
        assert calls[0].args == ('item-1', 'cycle-99')
        assert calls[1].args == ('item-2', 'cycle-99')

    @pytest.mark.asyncio
    async def test_saved_items_priority(self, mock_db):
        """Saved items appear before unsaved items (from get_notification_candidates)."""
        # The DB function returns saved first, then unsaved
        saved = _make_pool_item(id='saved-1', title='Saved Article',
                                saved_by_cortex=True,
                                saved_at='2026-01-15T11:00:00+00:00')
        unsaved = _make_pool_item(id='unsaved-1', title='Regular Article')
        mock_db.get_notification_candidates = AsyncMock(return_value=[saved, unsaved])

        notifications = await get_notifications()

        assert len(notifications) == 2
        assert notifications[0].content_id == 'saved-1'
        assert notifications[1].content_id == 'unsaved-1'

    @pytest.mark.asyncio
    async def test_expired_saved_items_cleaned(self, mock_db):
        """expire_saved_items is called before fetching candidates."""
        mock_db.get_notification_candidates = AsyncMock(return_value=[])

        await get_notifications()

        mock_db.expire_saved_items.assert_called_once_with(max_age_hours=48.0)

    @pytest.mark.asyncio
    async def test_graceful_on_missing_tables(self, mock_db):
        """Returns empty list if notification tables don't exist yet."""
        mock_db.get_notification_candidates = AsyncMock(
            side_effect=Exception("no such table: notification_log")
        )

        notifications = await get_notifications()

        assert notifications == []

    @pytest.mark.asyncio
    async def test_saved_items_skip_cooldown(self, mock_db):
        """Saved items surface even if they were recently surfaced (skip cooldown).

        The DB function get_notification_candidates returns saved items in a
        separate query that does not join notification_log for cooldown checking.
        """
        # Saved item is returned by DB even though it was recently surfaced
        saved = _make_pool_item(id='saved-1', title='Saved Article',
                                saved_by_cortex=True,
                                saved_at='2026-01-15T11:55:00+00:00')
        mock_db.get_notification_candidates = AsyncMock(return_value=[saved])

        notifications = await get_notifications()

        # The saved item should appear despite being recently surfaced
        assert len(notifications) == 1
        assert notifications[0].content_id == 'saved-1'

    @pytest.mark.asyncio
    async def test_source_diversity(self, mock_db):
        """get_notification_candidates is called with correct params for diversity.

        Source diversity filtering happens in db/content.py. The pipeline
        module delegates to it correctly.
        """
        # Simulate DB returning diverse results (it handles diversity internally)
        items = [
            _make_pool_item(id='a1', title='A1', source_channel='feed_a'),
            _make_pool_item(id='b1', title='B1', source_channel='feed_b'),
            _make_pool_item(id='c1', title='C1', source_channel='feed_c'),
        ]
        mock_db.get_notification_candidates = AsyncMock(return_value=items)

        notifications = await get_notifications()

        assert len(notifications) == 3
        sources = {n.source for n in notifications}
        assert len(sources) == 3  # all different sources

    @pytest.mark.asyncio
    async def test_saved_items_expire(self, mock_db):
        """Saved items older than 48h have expire called before fetch."""
        mock_db.get_notification_candidates = AsyncMock(return_value=[])

        await get_notifications()

        mock_db.expire_saved_items.assert_called_once_with(max_age_hours=48.0)


class TestFormatNotificationsText:
    """format_notifications_text() produces diegetic text."""

    def test_formats_solo_notifications(self):
        """Without visitor, shows direct feed text."""
        notifications = [
            Notification(
                content_id='item-1',
                title='Cool Article',
                source='rss_feed',
                content_type='article',
                surfaced_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            ),
        ]

        text = format_notifications_text(notifications, visitor_present=False)

        assert 'You notice some things in your feed' in text
        assert 'Cool Article' in text
        assert 'rss_feed' in text
        assert 'read_content' in text
        assert 'save_for_later' in text

    def test_formats_background_with_visitor(self):
        """With visitor present, notifications are marked as background."""
        notifications = [
            Notification(
                content_id='item-1',
                title='Something Interesting',
                source='blog',
                content_type='article',
                surfaced_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            ),
        ]

        text = format_notifications_text(notifications, visitor_present=True)

        assert 'In the background' in text
        assert 'Something Interesting' in text

    def test_empty_returns_empty_string(self):
        """No notifications produces empty string."""
        text = format_notifications_text([], visitor_present=False)
        assert text == ''

    def test_content_ids_in_text(self):
        """Content IDs appear in notification text for cortex to reference."""
        notifications = [
            Notification(
                content_id='abc-123',
                title='Test',
                source='feed',
                content_type='article',
                surfaced_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            ),
        ]

        text = format_notifications_text(notifications)

        assert 'abc-123' in text
