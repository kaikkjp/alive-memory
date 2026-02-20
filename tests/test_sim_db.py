"""Tests for sim.db — InMemoryDB for simulation."""

import pytest
import pytest_asyncio
from sim.db import InMemoryDB


@pytest_asyncio.fixture
async def memdb():
    db = await InMemoryDB.create()
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_create_and_init():
    db = await InMemoryDB.create()
    assert db.conn is not None
    await db.close()


@pytest.mark.asyncio
async def test_drives_state_singleton(memdb):
    row = await memdb.fetchone("SELECT * FROM drives_state WHERE id = 1")
    assert row is not None
    assert row['social_hunger'] == 0.5
    assert row['energy'] == 0.8


@pytest.mark.asyncio
async def test_engagement_state_singleton(memdb):
    row = await memdb.fetchone("SELECT * FROM engagement_state WHERE id = 1")
    assert row is not None
    assert row['status'] == 'none'


@pytest.mark.asyncio
async def test_room_state_singleton(memdb):
    row = await memdb.fetchone("SELECT * FROM room_state WHERE id = 1")
    assert row is not None
    assert row['shop_status'] == 'open'


@pytest.mark.asyncio
async def test_insert_event(memdb):
    await memdb.execute(
        "INSERT INTO events (id, event_type, source, content, created_at) VALUES (?, ?, ?, ?, ?)",
        ("e1", "visitor_message", "tg:user1", "Hello", "2026-02-01T09:00:00"),
    )
    await memdb.commit()
    row = await memdb.fetchone("SELECT * FROM events WHERE id = ?", ("e1",))
    assert row is not None
    assert row['event_type'] == 'visitor_message'
    assert row['content'] == 'Hello'


@pytest.mark.asyncio
async def test_insert_visitor(memdb):
    await memdb.execute(
        "INSERT INTO visitors (id, name, trust_level, visit_count) VALUES (?, ?, ?, ?)",
        ("v1", "Tanaka", "stranger", 1),
    )
    await memdb.commit()
    row = await memdb.fetchone("SELECT * FROM visitors WHERE id = ?", ("v1",))
    assert row['name'] == 'Tanaka'
    assert row['trust_level'] == 'stranger'


@pytest.mark.asyncio
async def test_cycle_log(memdb):
    await memdb.execute(
        "INSERT INTO cycle_log (cycle_number, routing_focus, trigger_type, action_taken, timestamp) VALUES (?, ?, ?, ?, ?)",
        (1, "idle", "ambient", "write_journal", "2026-02-01T09:05:00"),
    )
    await memdb.commit()
    rows = await memdb.fetchall("SELECT * FROM cycle_log")
    assert len(rows) == 1
    assert rows[0]['routing_focus'] == 'idle'


@pytest.mark.asyncio
async def test_drives_history(memdb):
    await memdb.execute(
        "INSERT INTO drives_state_history (social_hunger, curiosity, energy, mood_valence, mood_arousal, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (0.6, 0.4, 0.7, -0.2, 0.5, "2026-02-01T09:00:00"),
    )
    await memdb.commit()
    rows = await memdb.fetchall("SELECT * FROM drives_state_history")
    assert len(rows) == 1
    assert rows[0]['social_hunger'] == 0.6


@pytest.mark.asyncio
async def test_memory_pool(memdb):
    await memdb.execute(
        "INSERT INTO memory_pool (id, label, content, memory_type, salience, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("m1", "test_memory", "Something she remembers", "observation", 0.7, "2026-02-01T09:00:00"),
    )
    await memdb.commit()
    row = await memdb.fetchone("SELECT * FROM memory_pool WHERE id = ?", ("m1",))
    assert row['content'] == 'Something she remembers'


@pytest.mark.asyncio
async def test_threads(memdb):
    await memdb.execute(
        "INSERT INTO threads (id, thread_type, title, status, priority) VALUES (?, ?, ?, ?, ?)",
        ("t1", "question", "What is anti-pleasure?", "open", 0.8),
    )
    await memdb.commit()
    row = await memdb.fetchone("SELECT * FROM threads WHERE id = ?", ("t1",))
    assert row['title'] == 'What is anti-pleasure?'
    assert row['status'] == 'open'


@pytest.mark.asyncio
async def test_update_drives(memdb):
    await memdb.execute(
        "UPDATE drives_state SET mood_valence = ?, energy = ? WHERE id = 1",
        (-0.5, 0.3),
    )
    await memdb.commit()
    row = await memdb.fetchone("SELECT * FROM drives_state WHERE id = 1")
    assert row['mood_valence'] == -0.5
    assert row['energy'] == 0.3


@pytest.mark.asyncio
async def test_fetchall_empty(memdb):
    rows = await memdb.fetchall("SELECT * FROM events")
    assert rows == []


@pytest.mark.asyncio
async def test_close(memdb):
    await memdb.close()
    assert memdb.conn is None
