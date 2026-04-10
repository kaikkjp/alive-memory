"""Tests for semantic memory: totems, visitor traits, and visitor knowledge."""

import os
import tempfile

import pytest

from alive_memory.storage.sqlite import SQLiteStorage


@pytest.fixture
async def storage():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = SQLiteStorage(path)
    await s.initialize()
    yield s
    await s.close()
    os.unlink(path)


# ── Totems ────────────────────────────────────────────────────────


async def test_insert_and_get_totem(storage):
    totem_id = await storage.insert_totem(
        entity="transgender woman",
        visitor_id="caroline",
        weight=0.9,
        context="Caroline's gender identity",
        category="personal",
    )
    assert totem_id

    totems = await storage.get_totems(visitor_id="caroline")
    assert len(totems) == 1
    assert totems[0].entity == "transgender woman"
    assert totems[0].weight == 0.9
    assert totems[0].category == "personal"


async def test_search_totems(storage):
    await storage.insert_totem(entity="sushi", context="favorite food", category="preference")
    await storage.insert_totem(entity="Tokyo", context="dream travel destination", category="location")
    await storage.insert_totem(entity="guitar", context="plays acoustic guitar", category="general")

    results = await storage.search_totems("sushi food")
    assert len(results) >= 1
    assert any(t.entity == "sushi" for t in results)

    results = await storage.search_totems("Tokyo")
    assert len(results) >= 1
    assert results[0].entity == "Tokyo"


async def test_search_totems_empty_query(storage):
    results = await storage.search_totems("")
    assert results == []


async def test_update_totem_weight(storage):
    await storage.insert_totem(entity="coffee", weight=0.3)
    await storage.update_totem_weight("coffee", weight=0.8)

    totems = await storage.get_totems(min_weight=0.7)
    assert len(totems) == 1
    assert totems[0].weight == 0.8


async def test_get_totems_with_min_weight(storage):
    await storage.insert_totem(entity="low", weight=0.1)
    await storage.insert_totem(entity="high", weight=0.9)

    totems = await storage.get_totems(min_weight=0.5)
    assert len(totems) == 1
    assert totems[0].entity == "high"


async def test_totem_visitor_scoped(storage):
    await storage.insert_totem(entity="dogs", visitor_id="alice", weight=0.7)
    await storage.insert_totem(entity="cats", visitor_id="bob", weight=0.6)

    alice_totems = await storage.get_totems(visitor_id="alice")
    assert len(alice_totems) == 1
    assert alice_totems[0].entity == "dogs"


# ── Visitor Traits ────────────────────────────────────────────────


async def test_insert_and_get_trait(storage):
    trait_id = await storage.insert_trait(
        visitor_id="caroline",
        trait_category="demographic",
        trait_key="gender_identity",
        trait_value="transgender woman",
        confidence=0.95,
    )
    assert trait_id

    traits = await storage.get_traits("caroline")
    assert len(traits) == 1
    assert traits[0].trait_key == "gender_identity"
    assert traits[0].trait_value == "transgender woman"
    assert traits[0].confidence == 0.95


async def test_search_traits(storage):
    await storage.insert_trait(
        visitor_id="caroline",
        trait_category="personal",
        trait_key="occupation",
        trait_value="therapist",
    )
    await storage.insert_trait(
        visitor_id="bob",
        trait_category="preference",
        trait_key="favorite_color",
        trait_value="blue",
    )

    results = await storage.search_traits("therapist")
    assert len(results) >= 1
    assert results[0].trait_value == "therapist"

    results = await storage.search_traits("occupation")
    assert len(results) >= 1
    assert results[0].trait_key == "occupation"


async def test_search_traits_empty_query(storage):
    results = await storage.search_traits("")
    assert results == []


async def test_get_latest_trait(storage):
    await storage.insert_trait(
        visitor_id="alice",
        trait_category="preference",
        trait_key="favorite_food",
        trait_value="pizza",
    )
    await storage.insert_trait(
        visitor_id="alice",
        trait_category="preference",
        trait_key="favorite_food",
        trait_value="sushi",
    )

    latest = await storage.get_latest_trait("alice", "preference", "favorite_food")
    assert latest is not None
    assert latest.trait_value == "sushi"


async def test_get_latest_trait_not_found(storage):
    result = await storage.get_latest_trait("nobody", "x", "y")
    assert result is None


async def test_get_traits_by_category(storage):
    await storage.insert_trait("alice", "personal", "age", "30")
    await storage.insert_trait("alice", "preference", "color", "red")
    await storage.insert_trait("alice", "personal", "job", "engineer")

    personal = await storage.get_traits("alice", category="personal")
    assert len(personal) == 2
    assert all(t.trait_category == "personal" for t in personal)


# ── Visitors ──────────────────────────────────────────────────────


async def test_upsert_visitor_create(storage):
    await storage.upsert_visitor("v1", "Alice")
    visitor = await storage.get_visitor("v1")
    assert visitor is not None
    assert visitor.name == "Alice"
    assert visitor.trust_level == "stranger"
    assert visitor.visit_count == 1


async def test_upsert_visitor_update(storage):
    await storage.upsert_visitor("v1", "Alice")
    await storage.upsert_visitor(
        "v1", "Alice",
        emotional_imprint="warm and friendly",
        summary="Close friend who loves hiking",
    )

    visitor = await storage.get_visitor("v1")
    assert visitor.visit_count == 2
    assert visitor.emotional_imprint == "warm and friendly"
    assert visitor.summary == "Close friend who loves hiking"


async def test_search_visitors(storage):
    await storage.upsert_visitor("v1", "Alice", summary="Loves hiking and nature")
    await storage.upsert_visitor("v2", "Bob", summary="Software engineer")

    results = await storage.search_visitors("Alice")
    assert len(results) == 1
    assert results[0].name == "Alice"

    results = await storage.search_visitors("hiking")
    assert len(results) == 1
    assert results[0].name == "Alice"


async def test_upsert_visitor_promotes_placeholder_name(storage):
    """A visitor first seen by id-only gets a placeholder name (== id).
    When a later upsert supplies a real display name, the placeholder must
    be replaced — otherwise tg_12345 sticks forever and search_visitors("Alice")
    can never find this person."""
    await storage.upsert_visitor("tg_1", "tg_1")  # placeholder
    await storage.upsert_visitor("tg_1", "Alice")  # real name learned later

    visitor = await storage.get_visitor("tg_1")
    assert visitor.name == "Alice"
    assert visitor.visit_count == 2

    # Once a real name is in place, an accidental id-only call must NOT
    # blow it away — that would be a regression.
    await storage.upsert_visitor("tg_1", "tg_1")
    visitor = await storage.get_visitor("tg_1")
    assert visitor.name == "Alice"
    assert visitor.visit_count == 3


async def test_search_visitors_by_id(storage):
    """Stable IDs (e.g. tg_12345) must be searchable so reach-out can find them
    when only the ID — not a display name — is known."""
    await storage.upsert_visitor("tg_678830487", "tg_678830487")
    await storage.upsert_visitor("v2", "Bob")

    results = await storage.search_visitors("tg_678830487")
    assert len(results) == 1
    assert results[0].id == "tg_678830487"

    # Partial id match still works
    results = await storage.search_visitors("678830487")
    assert len(results) == 1
    assert results[0].id == "tg_678830487"


async def test_get_visitor_not_found(storage):
    result = await storage.get_visitor("nonexistent")
    assert result is None


# ── Fact Extraction ───────────────────────────────────────────────


async def test_trait_dedup():
    """Test trait dedup cooldown logic."""
    from alive_memory.consolidation.fact_extraction import _trait_is_duplicate

    cache: dict = {}

    # First write should not be duplicate
    assert not _trait_is_duplicate("v1", "personal", "age", "30", cache)
    # Same write immediately should be duplicate
    assert _trait_is_duplicate("v1", "personal", "age", "30", cache)
    # Different value should not be duplicate
    assert not _trait_is_duplicate("v1", "personal", "age", "31", cache)


async def test_consolidate_upserts_visitor_from_id_only(storage):
    """If a moment carries only visitor_id (no visitor_name), full sleep
    consolidation must still create the visitors row so search_visitors and
    proactive reach-out can find the person. Previously this was gated on
    both fields being present, leaving orphaned totems pointing at IDs with
    no visitors row."""
    from datetime import UTC, datetime

    from alive_memory.consolidation import consolidate
    from alive_memory.types import DayMoment, EventType

    moment = DayMoment(
        id="m-id-only",
        content="Quietly watches the window in the corner.",
        event_type=EventType.OBSERVATION,
        salience=0.3,
        valence=0.0,
        drive_snapshot={},
        timestamp=datetime.now(UTC),
        metadata={"visitor_id": "tg_678830487"},
    )
    await storage.record_moment(moment)

    await consolidate(storage)  # full depth, no llm/writer/reader needed

    visitor = await storage.get_visitor("tg_678830487")
    assert visitor is not None
    assert visitor.id == "tg_678830487"
    # No display name was supplied, so the id stands in for the name.
    assert visitor.name == "tg_678830487"


async def test_consolidate_promotes_name_within_batch(storage):
    """If two moments in the same consolidation batch share a visitor_id but
    only one carries a real visitor_name, the named moment must win — the
    earlier id-only moment must not lock in a placeholder for the whole run."""
    from datetime import UTC, datetime

    from alive_memory.consolidation import consolidate
    from alive_memory.types import DayMoment, EventType

    # Earlier moment: id only.
    m1 = DayMoment(
        id="m-1",
        content="Quietly watches the window.",
        event_type=EventType.OBSERVATION,
        salience=0.3,
        valence=0.0,
        drive_snapshot={},
        timestamp=datetime.now(UTC),
        metadata={"visitor_id": "tg_42"},
    )
    # Later moment in the same batch: id + real name.
    m2 = DayMoment(
        id="m-2",
        content="Says her name is Alice.",
        event_type=EventType.CONVERSATION,
        salience=0.4,
        valence=0.1,
        drive_snapshot={},
        timestamp=datetime.now(UTC),
        metadata={"visitor_id": "tg_42", "visitor_name": "Alice"},
    )
    await storage.record_moment(m1)
    await storage.record_moment(m2)

    await consolidate(storage)

    visitor = await storage.get_visitor("tg_42")
    assert visitor is not None
    assert visitor.name == "Alice"
    # Visit count should bump exactly once per consolidation run, regardless
    # of how many moments came from this visitor.
    assert visitor.visit_count == 1


async def test_visitor_backfill_from_orphaned_totems(storage):
    """The 006_visitor_backfill migration must create visitor rows for any
    visitor_id referenced by totems or visitor_traits but missing from the
    visitors table, derive first/last_visit from the source records' own
    timestamps (not migration time), and be idempotent."""
    await storage.insert_totem(
        entity="watches the window",
        visitor_id="tg_orphan_totem",
        weight=0.4,
    )
    await storage.insert_trait(
        visitor_id="tg_orphan_trait",
        trait_category="behavior",
        trait_key="presence",
        trait_value="quiet",
    )

    # Capture the source-record timestamps so we can assert the backfill
    # preserves them rather than stamping "now".
    conn = await storage._get_db()
    cursor = await conn.execute(
        "SELECT first_seen, last_referenced FROM totems WHERE visitor_id = ?",
        ("tg_orphan_totem",),
    )
    totem_first, totem_last = await cursor.fetchone()
    cursor = await conn.execute(
        "SELECT created_at FROM visitor_traits WHERE visitor_id = ?",
        ("tg_orphan_trait",),
    )
    (trait_created,) = await cursor.fetchone()

    # Simulate the broken pre-fix DB state: totems/traits exist, visitors empty.
    await conn.execute("DELETE FROM visitors")
    await conn.commit()
    assert await storage.get_visitor("tg_orphan_totem") is None
    assert await storage.get_visitor("tg_orphan_trait") is None

    # Re-running initialize() re-applies all migrations idempotently, which
    # in turn runs the backfill INSERT OR IGNORE.
    await storage.initialize()

    visitor_t = await storage.get_visitor("tg_orphan_totem")
    visitor_r = await storage.get_visitor("tg_orphan_trait")
    assert visitor_t is not None and visitor_t.name == "tg_orphan_totem"
    assert visitor_r is not None and visitor_r.name == "tg_orphan_trait"

    # Recency must come from the totem / trait records, not migration time.
    from datetime import datetime
    assert visitor_t.first_visit == datetime.fromisoformat(totem_first)
    assert visitor_t.last_visit == datetime.fromisoformat(totem_last)
    assert visitor_r.first_visit == datetime.fromisoformat(trait_created)
    assert visitor_r.last_visit == datetime.fromisoformat(trait_created)

    # Idempotency: running again must not duplicate or error.
    await storage.initialize()
    visitor_t_again = await storage.get_visitor("tg_orphan_totem")
    assert visitor_t_again is not None
    assert visitor_t_again.visit_count == 1


# ── Recall Integration ────────────────────────────────────────────


async def test_recall_includes_totems_and_traits(storage):
    """Recall should search totems and traits alongside grep."""
    import tempfile

    from alive_memory.hot.reader import MemoryReader
    from alive_memory.recall.hippocampus import recall
    from alive_memory.types import CognitiveState, DriveState, MoodState

    # Insert some facts
    await storage.insert_totem(
        entity="transgender woman",
        visitor_id="caroline",
        context="Caroline's gender identity",
        category="personal",
        weight=0.9,
    )
    await storage.insert_trait(
        visitor_id="caroline",
        trait_category="demographic",
        trait_key="gender_identity",
        trait_value="transgender woman",
        confidence=0.95,
    )

    # Create a temp memory dir for the reader
    with tempfile.TemporaryDirectory() as tmpdir:
        reader = MemoryReader(tmpdir)
        state = CognitiveState(
            mood=MoodState(), energy=0.8, drives=DriveState(),
            cycle_count=1, memories_total=0,
        )

        ctx = await recall(
            "gender identity transgender",
            reader, state,
            storage=storage,
        )

        assert len(ctx.totem_facts) >= 1
        assert len(ctx.trait_facts) >= 1
        assert any("transgender" in f for f in ctx.totem_facts)
        assert any("transgender" in f for f in ctx.trait_facts)


async def test_recall_without_storage():
    """Recall should work without storage (backward compat)."""
    import tempfile

    from alive_memory.hot.reader import MemoryReader
    from alive_memory.recall.hippocampus import recall
    from alive_memory.types import CognitiveState, DriveState, MoodState

    with tempfile.TemporaryDirectory() as tmpdir:
        reader = MemoryReader(tmpdir)
        state = CognitiveState(
            mood=MoodState(), energy=0.8, drives=DriveState(),
            cycle_count=1, memories_total=0,
        )

        # Should not raise
        ctx = await recall("hello", reader, state)
        assert ctx.totem_facts == []
        assert ctx.trait_facts == []
