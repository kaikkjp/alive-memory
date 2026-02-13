"""Tests for db.py — database layer with in-memory SQLite."""

import pytest
import db
from models.event import Event


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    """Use a temp database for each test, with singleton rows seeded."""
    db._db = None
    original_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "test.db")

    # Use init_db which creates schema + singleton rows
    await db.init_db()

    yield

    await db.close_db()
    db.DB_PATH = original_path


class TestRoomState:
    """Room state persistence."""

    @pytest.mark.asyncio
    async def test_get_default_room_state(self):
        state = await db.get_room_state()
        assert state is not None
        assert state.time_of_day in ('morning', 'afternoon', 'evening', 'night')

    @pytest.mark.asyncio
    async def test_update_room_state(self):
        await db.update_room_state(time_of_day='evening', weather='rain')
        state = await db.get_room_state()
        assert state.time_of_day == 'evening'
        assert state.weather == 'rain'


class TestDrivesState:
    """Drives state persistence."""

    @pytest.mark.asyncio
    async def test_get_default_drives(self):
        drives = await db.get_drives_state()
        assert drives is not None
        assert 0 <= drives.energy <= 1

    @pytest.mark.asyncio
    async def test_save_and_load_drives(self):
        drives = await db.get_drives_state()
        drives.energy = 0.42
        drives.mood_valence = -0.3
        await db.save_drives_state(drives)
        reloaded = await db.get_drives_state()
        assert abs(reloaded.energy - 0.42) < 0.001
        assert abs(reloaded.mood_valence - (-0.3)) < 0.001


class TestEvents:
    """Event creation and retrieval."""

    @pytest.mark.asyncio
    async def test_append_and_retrieve_event(self):
        event = Event(
            event_type='visitor_speech',
            source='visitor:test-id',
            payload={'text': 'hello'},
        )
        await db.append_event(event)
        events = await db.get_recent_events(limit=5)
        assert len(events) >= 1
        assert events[0].event_type == 'visitor_speech'

    @pytest.mark.asyncio
    async def test_event_payload_preserved(self):
        event = Event(
            event_type='visitor_speech',
            source='visitor:test',
            payload={'text': 'hello', 'lang': 'en'},
        )
        await db.append_event(event)
        events = await db.get_recent_events(limit=1)
        assert events[0].payload['text'] == 'hello'
        assert events[0].payload['lang'] == 'en'


class TestInbox:
    """Inbox — event queueing and reading."""

    @pytest.mark.asyncio
    async def test_inbox_add_and_read(self):
        # inbox requires a real event in the events table (FK constraint)
        event = Event(event_type='visitor_speech', source='visitor:x', payload={})
        await db.append_event(event)
        await db.inbox_add(event_id=event.id, priority=5)
        unread = await db.inbox_get_unread()
        assert any(e.id == event.id for e in unread)

    @pytest.mark.asyncio
    async def test_inbox_mark_read(self):
        event = Event(event_type='ambient', source='system', payload={})
        await db.append_event(event)
        await db.inbox_add(event_id=event.id, priority=1)
        unread = await db.inbox_get_unread()
        assert any(e.id == event.id for e in unread)
        await db.inbox_mark_read(event.id)
        unread_after = await db.inbox_get_unread()
        assert not any(e.id == event.id for e in unread_after)


class TestVisitors:
    """Visitor creation and updates."""

    @pytest.mark.asyncio
    async def test_create_and_get_visitor(self):
        await db.create_visitor(visitor_id='v-1')
        visitor = await db.get_visitor('v-1')
        assert visitor is not None
        assert visitor.id == 'v-1'
        assert visitor.trust_level == 'stranger'

    @pytest.mark.asyncio
    async def test_increment_visit(self):
        await db.create_visitor(visitor_id='v-2')
        await db.increment_visit('v-2')
        visitor = await db.get_visitor('v-2')
        assert visitor.visit_count >= 1


class TestJournal:
    """Journal entry creation and retrieval."""

    @pytest.mark.asyncio
    async def test_insert_and_retrieve_journal(self):
        await db.insert_journal(
            content='The morning was quiet.',
            mood='calm',
            tags=['morning', 'peace'],
            day_alive=1,
        )
        entries = await db.get_recent_journal(limit=5)
        assert len(entries) >= 1
        assert 'quiet' in entries[0].content


class TestCollection:
    """Collection item management."""

    @pytest.mark.asyncio
    async def test_insert_and_search_collection(self):
        await db.insert_collection_item({
            'id': 'test-item',
            'item_type': 'music',
            'title': 'Test Song',
            'location': 'shelf',
            'origin': 'appeared',
        })
        items = await db.search_collection(limit=10)
        assert any(i.title == 'Test Song' for i in items)


class TestEngagement:
    """Engagement state tracking."""

    @pytest.mark.asyncio
    async def test_get_default_engagement(self):
        state = await db.get_engagement_state()
        assert state is not None
        assert state.status == 'none'

    @pytest.mark.asyncio
    async def test_update_engagement(self):
        await db.update_engagement_state(
            status='engaged',
            visitor_id='v-1',
            context_id='ctx-1',
        )
        state = await db.get_engagement_state()
        assert state.status == 'engaged'
        assert state.visitor_id == 'v-1'


class TestTransaction:
    """Transaction context manager — atomic writes."""

    @pytest.mark.asyncio
    async def test_transaction_commits(self):
        event = Event(event_type='ambient', source='system', payload={'detail': 'test'})
        async with db.transaction():
            await db.append_event(event)
        events = await db.get_recent_events(limit=1)
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self):
        event = Event(event_type='ambient', source='system', payload={'detail': 'should_rollback'})
        try:
            async with db.transaction():
                await db.append_event(event)
                raise ValueError("Simulated error")
        except ValueError:
            pass
        events = await db.get_recent_events(limit=10)
        assert not any(
            e.payload.get('detail') == 'should_rollback'
            for e in events
        )
