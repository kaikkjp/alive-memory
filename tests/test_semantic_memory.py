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
