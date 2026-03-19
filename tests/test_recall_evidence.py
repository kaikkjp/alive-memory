"""Tests for trust-ordered recall, evidence assembly, and confidence scoring.

Covers:
- Phase 1: Raw turn storage and retrieval
- Phase 2: Trust-ordered recall assembly
- Phase 3: Token-budget packing
- Phase 4: Recency ranking
- Phase 5: Temporal hints
- Phase 6: Abstention / confidence
"""

from __future__ import annotations

import os
import tempfile

import pytest

from alive_memory import AliveMemory
from alive_memory.recall.evidence import compute_confidence, rank_with_recency
from alive_memory.recall.temporal import detect_temporal_hints
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import EvidenceBlock, RecallContext

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


# ── Phase 1: Raw turn storage ───────────────────────────────────────


@pytest.mark.asyncio
async def test_raw_turn_stored_at_intake() -> None:
    """Raw conversation turns are stored in cold_memory before salience gating."""
    embedder = FakeEmbedder()
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "test.db")
    memory = AliveMemory(
        storage=db, memory_dir=tmp, embedder=embedder,
        config={"intake": {"salience_threshold": 1.0}},  # block all moments
    )
    await memory.initialize()

    moment = await memory.intake(
        "conversation", "I live in Osaka",
        metadata={"session_id": "s1", "turn_id": 0, "role": "user"},
    )

    # Moment should be blocked by high salience threshold
    assert moment is None

    # But the raw turn should be stored in cold_memory
    turns = await memory.storage.get_turns_by_session("s1")
    assert len(turns) == 1
    assert turns[0]["content"] == "I live in Osaka"
    assert turns[0]["entry_type"] == "raw_turn"

    await memory.close()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_raw_turn_preserves_zero_turn_index() -> None:
    """Turn index 0 should be preserved (not treated as falsy)."""
    embedder = FakeEmbedder()
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "test.db")
    memory = AliveMemory(
        storage=db, memory_dir=tmp, embedder=embedder,
        config={"intake": {"salience_threshold": 0.0}},
    )
    await memory.initialize()

    await memory.intake(
        "conversation", "First turn",
        metadata={"session_id": "s1", "turn_index": 0, "role": "user"},
    )

    turns = await memory.storage.get_turns_by_session("s1")
    assert len(turns) == 1
    assert turns[0]["turn_index"] == 0  # must be 0, not None

    await memory.close()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_get_neighboring_turns(storage: SQLiteStorage) -> None:
    """Neighbor expansion returns surrounding context."""
    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    for i in range(10):
        await storage.store_cold_memory(
            content=f"turn {i}",
            embedding=vec,
            entry_type="raw_turn",
            session_id="sess-2",
            turn_index=i,
            role="user",
        )
    neighbors = await storage.get_neighboring_turns("sess-2", 5, window=2)
    assert len(neighbors) == 5  # turns 3,4,5,6,7
    assert neighbors[0]["turn_index"] == 3
    assert neighbors[-1]["turn_index"] == 7


@pytest.mark.asyncio
async def test_raw_turn_search_by_type(storage: SQLiteStorage) -> None:
    """search_cold_memory with entry_type='raw_turn' filters correctly."""
    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    await storage.store_cold_memory(content="event1", embedding=vec, entry_type="event")
    await storage.store_cold_memory(
        content="raw1", embedding=vec, entry_type="raw_turn",
        session_id="s1", turn_index=0, role="user",
    )
    raw_results = await storage.search_cold_memory(vec, entry_type="raw_turn")
    assert len(raw_results) == 1
    assert raw_results[0]["entry_type"] == "raw_turn"


# ── Phase 2: Trust-ordered recall ────────────────────────────────────


@pytest.mark.asyncio
async def test_recall_includes_raw_turns() -> None:
    """Recall should include raw turns in the output."""
    embedder = FakeEmbedder()
    vec = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    embedder.register("I live in Osaka", vec)
    embedder.register("Where do I live?", [0.95, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "test.db")
    memory = AliveMemory(storage=db, memory_dir=tmp, embedder=embedder)
    await memory.initialize()

    # Store a raw turn directly
    await memory.storage.store_cold_memory(
        content="[user]: I live in Osaka",
        embedding=vec,
        entry_type="raw_turn",
        raw_content="[user]: I live in Osaka",
        session_id="s1",
        turn_index=0,
        role="user",
    )

    ctx = await memory.recall("Where do I live?")
    assert len(ctx.raw_turns) > 0
    assert any("Osaka" in t for t in ctx.raw_turns)

    await memory.close()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def test_evidence_blocks_in_to_prompt() -> None:
    """to_prompt() should include raw turns section first."""
    ctx = RecallContext(
        raw_turns=["[user]: I live in Osaka"],
        journal_entries=["Discussed living situation"],
        query="Where do I live?",
    )
    prompt = ctx.to_prompt()
    assert "Verbatim Evidence" in prompt
    # Verbatim Evidence should appear before Recent Events
    verbatim_pos = prompt.index("Verbatim Evidence")
    events_pos = prompt.index("Recent Events")
    assert verbatim_pos < events_pos


# ── Phase 3: Token-budget packing ───────────────────────────────────


def test_pack_context_respects_budget() -> None:
    """Token-budget packing should stop adding when budget exhausted."""
    from benchmarks.academic.systems.alive_system import AliveMemorySystem

    system = AliveMemorySystem()
    ctx = RecallContext(
        raw_turns=["a" * 400] * 10,  # each ~100 tokens
        journal_entries=["b" * 400] * 10,
        query="test",
    )
    result = system._pack_context(ctx, token_budget=500)
    # Should not include all items
    assert len(result) < 8000  # not all 20 items


def test_pack_context_trust_order() -> None:
    """Higher-trust evidence should appear before lower-trust."""
    from benchmarks.academic.systems.alive_system import AliveMemorySystem

    system = AliveMemorySystem()
    ctx = RecallContext(
        raw_turns=["raw evidence here"],
        journal_entries=["journal entry here"],
        reflections=["reflection here"],
        evidence_blocks=[
            EvidenceBlock(text="raw evidence here", source_type="raw_turn", trust_rank=1),
            EvidenceBlock(text="journal entry here", source_type="journal", trust_rank=4),
            EvidenceBlock(text="reflection here", source_type="reflection", trust_rank=5),
        ],
        query="test",
    )
    result = system._pack_context(ctx, token_budget=10000)
    raw_pos = result.index("raw evidence")
    journal_pos = result.index("journal entry")
    reflection_pos = result.index("reflection here")
    assert raw_pos < journal_pos < reflection_pos


def test_pack_context_deduplicates() -> None:
    """Same text in multiple buckets should only appear once."""
    from benchmarks.academic.systems.alive_system import AliveMemorySystem

    system = AliveMemorySystem()
    ctx = RecallContext(
        raw_turns=["I live in Osaka"],
        journal_entries=["I live in Osaka"],  # duplicate
        query="test",
    )
    result = system._pack_context(ctx, token_budget=10000)
    assert result.count("I live in Osaka") == 1


# ── Phase 4: Recency ranking ────────────────────────────────────────


def test_rank_with_recency_prefers_newer() -> None:
    """At same trust rank, newer evidence should come first."""
    blocks = [
        EvidenceBlock(text="old", source_type="raw_turn", trust_rank=1,
                      timestamp="2026-01-01T00:00:00+00:00", score=0.8),
        EvidenceBlock(text="new", source_type="raw_turn", trust_rank=1,
                      timestamp="2026-03-19T00:00:00+00:00", score=0.8),
    ]
    ranked = rank_with_recency(blocks)
    assert ranked[0].text == "new"
    assert ranked[1].text == "old"


def test_rank_trust_before_recency() -> None:
    """Trust rank should always beat recency."""
    blocks = [
        EvidenceBlock(text="old raw", source_type="raw_turn", trust_rank=1,
                      timestamp="2026-01-01T00:00:00+00:00", score=0.8),
        EvidenceBlock(text="new reflection", source_type="reflection", trust_rank=5,
                      timestamp="2026-03-19T00:00:00+00:00", score=0.9),
    ]
    ranked = rank_with_recency(blocks)
    assert ranked[0].text == "old raw"


# ── Phase 5: Temporal hints ─────────────────────────────────────────


def test_detect_temporal_hints() -> None:
    """Should detect temporal operators in queries."""
    hints = detect_temporal_hints("What did I say before the trip?")
    assert hints.get("before") is True

    hints = detect_temporal_hints("When was the first time I mentioned dogs?")
    assert hints.get("when") is True
    assert hints.get("first") is True

    hints = detect_temporal_hints("What is the latest update on the project?")
    assert hints.get("latest") is True

    # "last" alone should NOT trigger "latest" (e.g. "last week" is a period)
    hints = detect_temporal_hints("What happened last time?")
    assert hints.get("latest") is None

    hints = detect_temporal_hints("What is the most recent change?")
    assert hints.get("latest") is True


def test_no_temporal_hints() -> None:
    """Normal queries should have no temporal hints."""
    hints = detect_temporal_hints("What is my favorite color?")
    assert len(hints) == 0


# ── Phase 6: Abstention / confidence ────────────────────────────────


def test_high_confidence_with_strong_raw_turns() -> None:
    """Strong raw turn evidence should give high confidence."""
    blocks = [
        EvidenceBlock(text="raw", source_type="raw_turn", trust_rank=1, score=0.8),
    ]
    confidence, abstain = compute_confidence(blocks, total_hits=5)
    assert confidence == 0.9
    assert abstain is False


def test_medium_confidence_with_facts_only() -> None:
    """Structured facts without raw turns should give medium confidence."""
    blocks = [
        EvidenceBlock(text="fact", source_type="totem", trust_rank=2, score=0.5),
    ]
    confidence, abstain = compute_confidence(blocks, total_hits=3)
    assert confidence == 0.6
    assert abstain is False


def test_low_confidence_with_no_evidence() -> None:
    """No evidence blocks should give low confidence and abstention."""
    confidence, abstain = compute_confidence([], total_hits=0)
    assert confidence == 0.1
    assert abstain is True


def test_some_hits_no_strong_evidence() -> None:
    """Some grep hits but no raw/fact blocks → low confidence, no abstention."""
    confidence, abstain = compute_confidence([], total_hits=5)
    assert confidence == 0.3
    assert abstain is False
