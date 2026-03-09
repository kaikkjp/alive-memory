"""Tests targeting remaining coverage gaps: hippocampus categorization, consolidation
pipeline, wake error paths, drives edge cases, writer collection, sqlite helpers,
evolution evaluate, and config edge cases."""

import os
import tempfile
import shutil
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alive_memory.config import AliveConfig, _load_yaml
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.recall.hippocampus import recall
from alive_memory.intake.drives import update_drives, update_mood, _valence_to_word, clamp
from alive_memory.consolidation.cold_search import find_cold_echoes
from alive_memory.storage.sqlite import (
    SQLiteStorage, _cosine_similarity, _serialize_embedding, _deserialize_embedding,
)
from alive_memory.types import (
    CognitiveState, DayMoment, DriveState, EventType,
    MoodState, Perception, SelfModel, SleepReport,
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="alive_exp2_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _make_state(**kwargs):
    defaults = dict(
        mood=MoodState(valence=0.0, arousal=0.5, word="neutral"),
        energy=0.8,
        drives=DriveState(social=0.5, curiosity=0.5, expression=0.5),
        cycle_count=1,
    )
    defaults.update(kwargs)
    return CognitiveState(**defaults)


def _make_moment(id="m1", content="test", **kwargs):
    defaults = dict(
        id=id,
        event_type=EventType.CONVERSATION,
        content=content,
        salience=0.5,
        valence=0.0,
        drive_snapshot={"social": 0.5, "curiosity": 0.5, "expression": 0.5},
        timestamp=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return DayMoment(**defaults)


# ── Hippocampus: all category branches ────────────────────────

async def test_recall_categorizes_visitors(tmp_dir):
    """Cover lines 55-57: visitor categorization in hippocampus."""
    visitors_dir = tmp_dir / "visitors"
    visitors_dir.mkdir()
    (visitors_dir / "alice.md").write_text("Alice loves gardening\n")

    self_dir = tmp_dir / "self"
    self_dir.mkdir()
    (self_dir / "identity.md").write_text("I am a shopkeeper.\n")

    reader = MemoryReader(tmp_dir)
    state = _make_state()
    ctx = await recall("alice gardening", reader, state)
    assert len(ctx.visitor_notes) >= 1


async def test_recall_categorizes_self(tmp_dir):
    """Cover lines 58-60: self categorization."""
    self_dir = tmp_dir / "self"
    self_dir.mkdir()
    (self_dir / "values.md").write_text("I value honesty and kindness\n")

    reader = MemoryReader(tmp_dir)
    state = _make_state()
    ctx = await recall("honesty kindness", reader, state)
    assert len(ctx.self_knowledge) >= 1


async def test_recall_categorizes_reflections(tmp_dir):
    """Cover lines 61-63: reflection categorization."""
    refl_dir = tmp_dir / "reflections"
    refl_dir.mkdir()
    (refl_dir / "2024-01-01.md").write_text("Today I reflected on gratitude deeply\n")

    self_dir = tmp_dir / "self"
    self_dir.mkdir()
    (self_dir / "identity.md").write_text("A bot.\n")

    reader = MemoryReader(tmp_dir)
    state = _make_state()
    ctx = await recall("gratitude deeply", reader, state)
    assert len(ctx.reflections) >= 1


async def test_recall_categorizes_threads(tmp_dir):
    """Cover lines 64-66: thread categorization."""
    threads_dir = tmp_dir / "threads"
    threads_dir.mkdir()
    (threads_dir / "abc123.md").write_text("Discussion about quantum physics\n")

    self_dir = tmp_dir / "self"
    self_dir.mkdir()
    (self_dir / "identity.md").write_text("A bot.\n")

    reader = MemoryReader(tmp_dir)
    state = _make_state()
    ctx = await recall("quantum physics", reader, state)
    assert len(ctx.thread_context) >= 1


# ── Drives: uncovered branches ────────────────────────────────

def test_drives_action_event():
    """Cover line 81: ACTION event type branch."""
    drives = DriveState(social=0.5, curiosity=0.5, expression=0.8)
    perceptions = [
        Perception(
            event_type=EventType.ACTION,
            content="painted a picture",
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    result = update_drives(drives, perceptions, 1.0)
    assert result.expression < drives.expression  # expression relief


def test_drives_observation_event():
    """Cover line 85: OBSERVATION event type branch."""
    drives = DriveState(social=0.5, curiosity=0.3, expression=0.5)
    perceptions = [
        Perception(
            event_type=EventType.OBSERVATION,
            content="saw a rare bird",
            salience=0.8,
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    result = update_drives(drives, perceptions, 0.1)
    # curiosity should increase from observation
    assert result.curiosity >= drives.curiosity


def test_drives_extreme_homeostasis():
    """Cover line 66: extreme distance homeostatic pull (distance > 0.5)."""
    drives = DriveState(social=0.0, curiosity=0.0, expression=0.0, rest=0.0)
    result = update_drives(drives, [], 10.0)
    # Should pull toward 0.5 more aggressively
    assert result.social > 0.0
    assert result.curiosity > 0.0


def test_mood_social_hunger_pressure():
    """Cover lines 113-115: social hunger valence suppression."""
    mood = MoodState(valence=0.5, arousal=0.5, word="content")
    drives = DriveState(social=0.9, curiosity=0.5, expression=0.5)
    result = update_mood(mood, drives, [], 1.0)
    # Social hunger should push valence down
    assert result.valence < mood.valence


def test_mood_expression_frustration():
    """Cover lines 125-126: expression frustration."""
    mood = MoodState(valence=0.5, arousal=0.5, word="content")
    drives = DriveState(social=0.3, curiosity=0.5, expression=0.9)
    result = update_mood(mood, drives, [], 1.0)
    assert result.valence < mood.valence


def test_mood_conversation_event():
    """Cover lines 119-122: conversation event in mood update."""
    mood = MoodState(valence=0.0, arousal=0.3, word="neutral")
    drives = DriveState(social=0.8, curiosity=0.5, expression=0.5)
    perceptions = [
        Perception(
            event_type=EventType.CONVERSATION,
            content="hello",
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    result = update_mood(mood, drives, perceptions, 1.0)
    # Conversation should lift arousal
    assert result.arousal >= 0.3


def test_mood_large_delta_clamp():
    """Cover lines 131-132: delta clamp prevents large swings."""
    mood = MoodState(valence=-0.5, arousal=0.5, word="sad")
    drives = DriveState(social=0.3, curiosity=0.5, expression=0.3)
    # Many perceptions to create large positive shift
    perceptions = [
        Perception(event_type=EventType.CONVERSATION, content="hi", salience=0.5,
                   timestamp=datetime.now(timezone.utc))
        for _ in range(20)
    ]
    result = update_mood(mood, drives, perceptions, 1.0)
    # Delta should be clamped to max_delta (0.10)
    assert abs(result.valence - mood.valence) <= 0.11  # small tolerance


def test_mood_hard_floor():
    """Cover line 135: hard floor at -0.85."""
    mood = MoodState(valence=-0.85, arousal=0.5, word="sad")
    drives = DriveState(social=0.9, curiosity=0.5, expression=0.9)
    result = update_mood(mood, drives, [], 10.0)
    assert result.valence >= -0.85


def test_valence_to_word_all_branches():
    """Cover lines 149-162: all mood word branches."""
    assert _valence_to_word(0.5, 0.8) == "excited"
    assert _valence_to_word(0.5, 0.3) == "content"
    assert _valence_to_word(-0.5, 0.8) == "anxious"
    assert _valence_to_word(-0.5, 0.3) == "melancholy"
    assert _valence_to_word(0.0, 0.8) == "alert"
    assert _valence_to_word(0.0, 0.2) == "drowsy"
    assert _valence_to_word(0.0, 0.5) == "neutral"


# ── Writer: append_collection ─────────────────────────────────

def test_writer_append_collection(tmp_dir):
    """Cover lines 193-202: append_collection method."""
    collection_dir = tmp_dir / "collection"
    collection_dir.mkdir()

    writer = MemoryWriter(tmp_dir)
    path = writer.append_collection("Rare Items", "A golden compass was found.")
    assert path.exists()
    content = path.read_text()
    assert "golden compass" in content


def test_writer_append_collection_existing(tmp_dir):
    """Test appending to existing collection file."""
    collection_dir = tmp_dir / "collection"
    collection_dir.mkdir()
    (collection_dir / "rare_items.md").write_text("# Rare Items\n\nExisting item.\n\n")

    writer = MemoryWriter(tmp_dir)
    writer.append_collection("Rare Items", "A new item appeared.")
    content = (collection_dir / "rare_items.md").read_text()
    assert "Existing item" in content
    assert "new item" in content


# ── Config: _load_yaml error paths ────────────────────────────

def test_load_yaml_with_pyyaml(tmp_dir):
    """Cover lines 77-79: normal YAML loading with pyyaml."""
    yaml_file = tmp_dir / "config.yaml"
    yaml_file.write_text("key: value\n")
    result = _load_yaml(yaml_file)
    assert result.get("key") == "value"


def test_load_yaml_nonexistent_file():
    """Cover lines 83-85: YAML load failure returns empty dict."""
    result = _load_yaml(Path("/nonexistent/file.yaml"))
    assert result == {}


def test_load_yaml_fallback_no_pyyaml(tmp_dir):
    """Cover lines 80-82: fallback to _parse_simple_yaml when yaml not available."""
    import alive_memory.config as cfg_mod
    yaml_file = tmp_dir / "config.yaml"
    yaml_file.write_text("section:\n  key: 42\n")
    # Directly test the fallback path
    result = cfg_mod._parse_simple_yaml(yaml_file)
    assert result["section"]["key"] == 42


def test_config_from_nonexistent_yaml():
    """Cover config with missing file path."""
    cfg = AliveConfig("/nonexistent/path.yaml")
    assert cfg.get("anything") is None


# ── SQLite helpers ────────────────────────────────────────────

def test_cosine_similarity_mismatch():
    """Cover line 702-703: mismatched vector lengths."""
    assert _cosine_similarity([1, 2], [1, 2, 3]) == 0.0


def test_cosine_similarity_zero_vector():
    """Cover lines 707-708: zero vectors."""
    assert _cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0
    assert _cosine_similarity([1, 2, 3], [0, 0, 0]) == 0.0


def test_cosine_similarity_normal():
    """Normal cosine similarity."""
    result = _cosine_similarity([1, 0, 0], [1, 0, 0])
    assert abs(result - 1.0) < 0.001


def test_serialize_deserialize_embedding():
    """Cover serialize/deserialize roundtrip."""
    original = [1.0, 2.0, 3.0, 4.0]
    blob = _serialize_embedding(original)
    restored = _deserialize_embedding(blob)
    assert len(restored) == 4
    for a, b in zip(original, restored):
        assert abs(a - b) < 0.001


def test_serialize_none():
    assert _serialize_embedding(None) is None
    assert _deserialize_embedding(None) is None


# ── SQLite Storage: integration paths ─────────────────────────

@pytest.fixture
async def storage(tmp_dir):
    db_path = str(tmp_dir / "test.db")
    s = SQLiteStorage(db_path)
    await s.initialize()
    yield s
    await s.close()


async def test_storage_flush_stale_moments(storage):
    """Cover storage.flush_stale_moments."""
    result = await storage.flush_stale_moments(72)
    assert result >= 0


async def test_storage_cold_search_empty(storage):
    """Cover cold search on empty database."""
    results = await storage.search_cold([0.1, 0.2, 0.3], limit=5)
    assert results == []


async def test_storage_store_and_search_cold(storage):
    """Cover cold embedding store and search."""
    embedding = [1.0, 0.0, 0.0]
    await storage.store_cold_embedding(
        content="Test memory about gardening",
        embedding=embedding,
        source_moment_id="m-test-1",
        metadata={"event_type": "conversation"},
    )
    results = await storage.search_cold([1.0, 0.0, 0.0], limit=5)
    assert len(results) >= 1


async def test_storage_record_and_get_moments(storage):
    """Cover moment recording and retrieval."""
    moment = _make_moment(id="m-store-1", content="A test moment")
    await storage.record_moment(moment)
    moments = await storage.get_unprocessed_moments()
    assert len(moments) >= 1
    assert any(m.id == "m-store-1" for m in moments)


async def test_storage_mark_moment_processed(storage):
    """Cover mark_moment_processed."""
    moment = _make_moment(id="m-mark-1", content="Mark me")
    await storage.record_moment(moment)
    await storage.mark_moment_processed("m-mark-1")
    moments = await storage.get_unprocessed_moments()
    assert not any(m.id == "m-mark-1" for m in moments)


async def test_storage_flush_day_memory(storage):
    """Cover flush_day_memory."""
    moment = _make_moment(id="m-flush-1", content="Flush me")
    await storage.record_moment(moment)
    await storage.mark_moment_processed("m-flush-1")
    result = await storage.flush_day_memory()
    assert result >= 0


async def test_storage_log_consolidation(storage):
    """Cover log_consolidation."""
    report = SleepReport(depth="full")
    report.moments_processed = 3
    report.duration_ms = 100
    await storage.log_consolidation(report)


# ── Consolidation pipeline paths ──────────────────────────────

async def test_consolidation_nap_mode(tmp_dir):
    """Cover consolidation nap mode path (lines 78-81)."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    moments = [_make_moment(id=f"m{i}", content=f"Moment {i}", salience=0.3 + i * 0.1)
               for i in range(8)]
    storage.get_unprocessed_moments.return_value = moments
    storage.mark_moment_processed = AsyncMock()
    storage.log_consolidation = AsyncMock()

    writer = MagicMock()
    writer.append_journal = MagicMock()

    report = await consolidate(storage, writer=writer, depth="nap")
    assert report.depth == "nap"
    # Nap processes top 5 by default
    assert report.moments_processed <= 5


async def test_consolidation_no_moments():
    """Cover early return when no moments (lines 73-75)."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    storage.get_unprocessed_moments.return_value = []
    storage.log_consolidation = AsyncMock()

    report = await consolidate(storage, depth="full")
    assert report.moments_processed == 0


async def test_consolidation_no_llm_writes_raw(tmp_dir):
    """Cover lines 122-129: no LLM writes raw moment to journal."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    moments = [_make_moment(id="m1", content="Raw moment content")]
    storage.get_unprocessed_moments.return_value = moments
    storage.mark_moment_processed = AsyncMock()
    storage.flush_day_memory = AsyncMock()
    storage.log_consolidation = AsyncMock()

    writer = MagicMock()
    writer.append_journal = MagicMock()
    writer.append_reflection = MagicMock()

    report = await consolidate(storage, writer=writer, depth="full")
    assert report.journal_entries_written == 1
    writer.append_journal.assert_called_once()


async def test_consolidation_full_with_embedder(tmp_dir):
    """Cover lines 159-178: batch embed to cold archive."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    moments = [_make_moment(id="m1", content="Embed me")]
    storage.get_unprocessed_moments.return_value = moments
    storage.mark_moment_processed = AsyncMock()
    storage.flush_day_memory = AsyncMock()
    storage.store_cold_embedding = AsyncMock()
    storage.log_consolidation = AsyncMock()

    embedder = AsyncMock()
    embedder.embed.return_value = [0.1, 0.2, 0.3]

    writer = MagicMock()
    writer.append_journal = MagicMock()
    writer.append_reflection = MagicMock()

    report = await consolidate(storage, writer=writer, embedder=embedder, depth="full")
    assert report.cold_embeddings_added == 1


async def test_consolidation_embed_failure(tmp_dir):
    """Cover line 176-177: embed failure logging."""
    from alive_memory.consolidation import consolidate

    storage = AsyncMock()
    moments = [_make_moment(id="m1", content="Fail embed")]
    storage.get_unprocessed_moments.return_value = moments
    storage.mark_moment_processed = AsyncMock()
    storage.flush_day_memory = AsyncMock()
    storage.store_cold_embedding = AsyncMock(side_effect=Exception("embed fail"))
    storage.log_consolidation = AsyncMock()

    embedder = AsyncMock()
    embedder.embed.return_value = [0.1, 0.2, 0.3]

    writer = MagicMock()
    writer.append_journal = MagicMock()
    writer.append_reflection = MagicMock()

    report = await consolidate(storage, writer=writer, embedder=embedder, depth="full")
    assert report.cold_embeddings_added == 0


# ── Wake: error-handling paths ────────────────────────────────

async def test_wake_hook_failures():
    """Cover wake.py lines 91-92, 99-100, 105-106: hook exception handling."""
    from alive_memory.consolidation.wake import run_wake_transition, WakeConfig

    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.flush_day_memory = AsyncMock(return_value=0)

    hooks = AsyncMock()
    hooks.manage_threads = AsyncMock(side_effect=Exception("thread fail"))
    hooks.cleanup_pool = AsyncMock(side_effect=Exception("pool fail"))
    hooks.reset_drives = AsyncMock(side_effect=Exception("drive fail"))
    hooks.update_self_files = AsyncMock(side_effect=Exception("self fail"))

    report = await run_wake_transition(storage, hooks=hooks, config=WakeConfig())
    # Should complete despite all hook failures
    assert report.duration_ms >= 0


async def test_wake_sdk_flush_failure():
    """Cover wake.py lines 115-116: flush_stale_moments failure."""
    from alive_memory.consolidation.wake import run_wake_transition, WakeConfig

    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(side_effect=Exception("flush fail"))
    storage.flush_day_memory = AsyncMock(return_value=0)

    report = await run_wake_transition(storage, config=WakeConfig())
    assert report.duration_ms >= 0


async def test_wake_flush_day_memory_failure():
    """Cover wake.py lines 148-149: flush_day_memory failure."""
    from alive_memory.consolidation.wake import run_wake_transition, WakeConfig

    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.flush_day_memory = AsyncMock(side_effect=Exception("flush fail"))

    report = await run_wake_transition(storage, config=WakeConfig())
    assert report.duration_ms >= 0


async def test_wake_embedder_failure():
    """Cover wake.py lines 137-143: embedder failure during wake."""
    from alive_memory.consolidation.wake import run_wake_transition, WakeConfig

    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.flush_day_memory = AsyncMock(return_value=0)
    storage.get_unprocessed_moments = AsyncMock(return_value=[
        _make_moment(id="m1", content="embed me"),
    ])
    storage.store_cold_embedding = AsyncMock(side_effect=Exception("embed fail"))

    embedder = AsyncMock()
    embedder.embed = AsyncMock(side_effect=Exception("embed error"))

    report = await run_wake_transition(storage, embedder=embedder, config=WakeConfig())
    assert report.cold_embeddings_added == 0


async def test_wake_embedder_success():
    """Cover wake.py lines 120-141: successful embedding during wake."""
    from alive_memory.consolidation.wake import run_wake_transition, WakeConfig

    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.flush_day_memory = AsyncMock(return_value=0)
    storage.get_unprocessed_moments = AsyncMock(return_value=[
        _make_moment(id="m1", content="embed me"),
    ])
    storage.store_cold_embedding = AsyncMock()

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    report = await run_wake_transition(storage, embedder=embedder, config=WakeConfig())
    assert report.cold_embeddings_added == 1


# ── Cold search ───────────────────────────────────────────────

async def test_find_cold_echoes():
    """Cover cold_search.py: successful cold echo search."""
    storage = AsyncMock()
    storage.search_cold = AsyncMock(return_value=[
        {"content": "old memory", "score": 0.9, "id": "c1"},
    ])

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    moment = _make_moment(id="m1", content="test query")
    echoes = await find_cold_echoes(moment, storage, embedder, limit=3)
    assert len(echoes) >= 1


async def test_find_cold_echoes_embed_failure():
    """Cover cold_search.py lines 43-45: embed failure returns empty."""
    storage = AsyncMock()
    embedder = AsyncMock()
    embedder.embed = AsyncMock(side_effect=Exception("embed fail"))

    moment = _make_moment(id="m1", content="test query")
    echoes = await find_cold_echoes(moment, storage, embedder, limit=3)
    assert echoes == []


# ── Evolution: _evaluate_drift_result branches ────────────────

async def test_evolution_evaluate_drift_result_none():
    """Cover evolution.py line 176: severity='none'."""
    from alive_memory.identity.evolution import IdentityEvolution
    from alive_memory.identity.drift import DriftResult

    storage = AsyncMock()
    engine = IdentityEvolution(storage)
    result = DriftResult(composite_score=0.01, severity="none")
    decision = await engine.evaluate(result)
    assert decision.action == "defer"


async def test_evolution_evaluate_drift_result_significant():
    """Cover evolution.py lines 183-188: severity='significant'."""
    from alive_memory.identity.evolution import IdentityEvolution
    from alive_memory.identity.drift import DriftResult

    storage = AsyncMock()
    engine = IdentityEvolution(storage)
    result = DriftResult(composite_score=0.8, severity="significant")
    decision = await engine.evaluate(result)
    assert decision.action == "accept"


async def test_evolution_evaluate_drift_result_notable():
    """Cover evolution.py lines 190-194: severity='notable'."""
    from alive_memory.identity.evolution import IdentityEvolution
    from alive_memory.identity.drift import DriftResult

    storage = AsyncMock()
    engine = IdentityEvolution(storage)
    result = DriftResult(composite_score=0.4, severity="notable")
    decision = await engine.evaluate(result)
    assert decision.action == "defer"
    assert "review" in decision.reason


# ── Reader: error handling paths ──────────────────────────────

def test_reader_grep_unreadable_file(tmp_dir):
    """Cover reader.py lines 70-71: OSError/UnicodeDecodeError handling."""
    journal_dir = tmp_dir / "journal"
    journal_dir.mkdir()
    # Write binary content that will cause UnicodeDecodeError
    (journal_dir / "bad.md").write_bytes(b"\x80\x81\x82\x83" * 100)

    reader = MemoryReader(tmp_dir)
    # Should not raise, just skip the bad file
    results = reader.grep_memory("test")
    assert isinstance(results, list)


def test_reader_recent_journal_unreadable(tmp_dir):
    """Cover reader.py lines 147-148: journal read error handling."""
    journal_dir = tmp_dir / "journal"
    journal_dir.mkdir()
    (journal_dir / "2024-01-01.md").write_bytes(b"\x80\x81\x82\x83" * 100)

    reader = MemoryReader(tmp_dir)
    entries = reader.read_recent_journal(days=30)
    assert isinstance(entries, list)


def test_reader_recent_reflections_unreadable(tmp_dir):
    """Cover reader.py lines 200-201: reflections read error handling."""
    refl_dir = tmp_dir / "reflections"
    refl_dir.mkdir()
    (refl_dir / "2024-01-01.md").write_bytes(b"\x80\x81\x82\x83" * 100)

    reader = MemoryReader(tmp_dir)
    entries = reader.read_recent_reflections(days=30)
    assert isinstance(entries, list)
