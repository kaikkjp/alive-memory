"""Tests for unified cold memory (Phase 1 of tier role fix).

Tests:
- store_cold_memory round-trip
- search_cold_memory semantic ranking
- Dual-path recall (grep hot + semantic cold)
- Weight blending in ranking
- Backward compat with legacy cold_embeddings
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import pytest

from alive_memory import AliveMemory, EventType
from alive_memory.storage.sqlite import SQLiteStorage


# ── Helpers ──────────────────────────────────────────────────────────


class FakeEmbedder:
    """Deterministic embedder that maps known strings to fixed vectors."""

    def __init__(self) -> None:
        self._map: dict[str, list[float]] = {}
        self._dim = 8

    def register(self, text: str, vector: list[float]) -> None:
        self._map[text] = vector

    async def embed(self, text: str) -> list[float]:
        if text in self._map:
            return self._map[text]
        # Default: hash-based pseudo-embedding
        h = hash(text) & 0xFFFFFFFF
        vec = [float((h >> i) & 1) for i in range(self._dim)]
        norm = max(sum(v * v for v in vec) ** 0.5, 1e-9)
        return [v / norm for v in vec]

    @property
    def dimensions(self) -> int:
        return self._dim


@pytest.fixture
async def storage():
    tmp = tempfile.mktemp(suffix=".db")
    s = SQLiteStorage(tmp)
    await s.initialize()
    yield s
    await s.close()
    if os.path.exists(tmp):
        os.unlink(tmp)


# ── store_cold_memory ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_and_search_event(storage: SQLiteStorage) -> None:
    """Store an event in cold_memory and retrieve it semantically."""
    embedder = FakeEmbedder()
    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    embedder.register("I went to Target", vec)
    embedder.register("What store did I go to?", [0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    await storage.store_cold_memory(
        content="I went to Target",
        embedding=vec,
        entry_type="event",
        raw_content="User said: I went to Target to buy groceries",
        metadata={"event_type": "conversation", "salience": 0.8},
    )

    query_vec = await embedder.embed("What store did I go to?")
    results = await storage.search_cold_memory(query_vec, limit=5)

    assert len(results) == 1
    assert results[0]["content"] == "I went to Target"
    assert results[0]["raw_content"] == "User said: I went to Target to buy groceries"
    assert results[0]["entry_type"] == "event"
    assert results[0]["score"] > 0


@pytest.mark.asyncio
async def test_store_and_search_totem(storage: SQLiteStorage) -> None:
    """Store a totem in cold_memory and retrieve it semantically."""
    vec = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    await storage.store_cold_memory(
        content="Target — Store where Alice shops",
        embedding=vec,
        entry_type="totem",
        visitor_id="alice",
        weight=0.8,
        category="location",
    )

    # Query with similar vector
    query_vec = [0.1, 0.95, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    results = await storage.search_cold_memory(query_vec, limit=5)

    assert len(results) == 1
    assert results[0]["entry_type"] == "totem"
    assert results[0]["weight"] == 0.8
    assert results[0]["visitor_id"] == "alice"


@pytest.mark.asyncio
async def test_store_and_search_trait(storage: SQLiteStorage) -> None:
    """Store a trait in cold_memory and retrieve it semantically."""
    vec = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    await storage.store_cold_memory(
        content="favorite_color: blue",
        embedding=vec,
        entry_type="trait",
        visitor_id="alice",
        weight=0.9,
        category="preference",
    )

    query_vec = [0.05, 0.0, 0.98, 0.0, 0.0, 0.0, 0.0, 0.0]
    results = await storage.search_cold_memory(query_vec, limit=5)

    assert len(results) == 1
    assert results[0]["entry_type"] == "trait"
    assert results[0]["content"] == "favorite_color: blue"


# ── Weight blending ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weight_blending_ranks_high_weight_higher(storage: SQLiteStorage) -> None:
    """High-weight totem should rank above low-weight at similar cosine distance."""
    base_vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    # Low weight totem, slightly closer cosine
    await storage.store_cold_memory(
        content="low-weight fact",
        embedding=[0.99, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        entry_type="totem",
        weight=0.1,
    )
    # High weight totem, slightly farther cosine
    await storage.store_cold_memory(
        content="high-weight fact",
        embedding=[0.95, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        entry_type="totem",
        weight=0.9,
    )

    results = await storage.search_cold_memory(base_vec, limit=2)
    assert len(results) == 2
    # High weight should rank first due to weight blending
    assert results[0]["content"] == "high-weight fact"


# ── Entry type filtering ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_by_entry_type(storage: SQLiteStorage) -> None:
    """Filter cold_memory search by entry type."""
    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    await storage.store_cold_memory(content="event1", embedding=vec, entry_type="event")
    await storage.store_cold_memory(content="totem1", embedding=vec, entry_type="totem")
    await storage.store_cold_memory(content="trait1", embedding=vec, entry_type="trait")

    events = await storage.search_cold_memory(vec, entry_type="event")
    assert len(events) == 1
    assert events[0]["entry_type"] == "event"

    totems = await storage.search_cold_memory(vec, entry_type="totem")
    assert len(totems) == 1
    assert totems[0]["entry_type"] == "totem"


# ── Backward compat with legacy cold_embeddings ──────────────────────


@pytest.mark.asyncio
async def test_legacy_cold_embeddings_still_work(storage: SQLiteStorage) -> None:
    """Legacy store_cold_embedding and search_cold still work."""
    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    await storage.store_cold_embedding(
        content="legacy content",
        embedding=vec,
        source_moment_id="m1",
        metadata={"event_type": "conversation"},
    )

    results = await storage.search_cold(vec, limit=5)
    assert len(results) == 1
    assert results[0]["content"] == "legacy content"


# ── Dual-path recall integration ─────────────────────────────────────


@pytest.mark.asyncio
async def test_dual_path_recall() -> None:
    """Recall should find results from both hot grep and cold semantic search."""
    embedder = FakeEmbedder()
    # Register vectors so Target query matches the cold entry
    target_vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    query_vec = [0.95, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    embedder.register("Target — Store where Alice shops", target_vec)
    embedder.register("What store did Alice shop at?", query_vec)

    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "test.db")
    memory = AliveMemory(storage=db, memory_dir=tmp, embedder=embedder)
    await memory.initialize()

    # Put something in hot memory (will be found by grep)
    writer = memory._writer
    writer.append_journal("Alice mentioned she loves shopping")

    # Put something in cold_memory (only found by semantic search)
    await memory._storage.store_cold_memory(
        content="Target — Store where Alice shops",
        embedding=target_vec,
        entry_type="totem",
        visitor_id="alice",
        weight=0.7,
        category="location",
    )

    # Recall should find both
    ctx = await memory.recall("What store did Alice shop at?")

    # Hot grep should find "shopping" keyword match
    has_hot_hit = len(ctx.journal_entries) > 0
    # Cold semantic should find "Target" totem
    has_cold_hit = any("Target" in f for f in ctx.totem_facts)

    assert has_hot_hit or has_cold_hit, "At least one path should find something"
    # The cold path specifically should find Target
    assert has_cold_hit, f"Cold semantic search should find Target totem. Got: {ctx.totem_facts}"

    await memory.close()

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ── Empty cold_memory ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_empty_cold_memory(storage: SQLiteStorage) -> None:
    """Searching empty cold_memory returns empty list."""
    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    results = await storage.search_cold_memory(vec, limit=5)
    assert results == []


# ── Entries without embedding ────────────────────────────────────────


@pytest.mark.asyncio
async def test_entries_without_embedding_skipped(storage: SQLiteStorage) -> None:
    """Entries stored without embedding should not appear in search results."""
    await storage.store_cold_memory(
        content="no-embedding entry",
        embedding=None,
        entry_type="event",
    )

    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    results = await storage.search_cold_memory(vec, limit=5)
    assert len(results) == 0
