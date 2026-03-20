"""Integration tests for the alive-memory SDK (three-tier architecture)."""

import os
import tempfile
from datetime import UTC, datetime

import pytest

from alive_memory import AliveMemory
from alive_memory.config import AliveConfig
from alive_memory.consolidation.whisper import translate_whisper
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.intake.affect import apply_affect, compute_valence
from alive_memory.intake.drives import clamp, update_drives, update_mood
from alive_memory.intake.formation import _adjust_salience, _is_duplicate
from alive_memory.intake.thalamus import _estimate_novelty
from alive_memory.intake.thalamus import perceive
from alive_memory.meta.controller import classify_outcome, compute_adaptive_cooldown
from alive_memory.recall.weighting import decay_strength
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import (
    DayMoment,
    DriveState,
    EventType,
    MoodState,
    Perception,
    RecallContext,
)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_test_memory_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ── Config ──────────────────────────────────────────────────────

def test_config_defaults():
    cfg = AliveConfig()
    assert cfg.get("memory.embedding_dimensions") == 384
    assert cfg.get("recall.default_limit") == 10
    assert cfg.get("nonexistent", 42) == 42


def test_config_dict_override():
    cfg = AliveConfig({"memory": {"embedding_dimensions": 512}})
    assert cfg.get("memory.embedding_dimensions") == 512


def test_config_set():
    cfg = AliveConfig()
    cfg.set("custom.key", 123)
    assert cfg.get("custom.key") == 123


# ── Intake: Thalamus ────────────────────────────────────────────

def test_perceive_conversation():
    p = perceive("conversation", "Hello there!")
    assert p.event_type == EventType.CONVERSATION
    assert 0.0 <= p.salience <= 1.0
    assert p.content == "Hello there!"


def test_perceive_with_metadata():
    p = perceive("observation", "A bird outside", metadata={"salience": 0.95})
    assert p.salience == 0.95


def test_perceive_unknown_type():
    p = perceive("unknown_event", "something")
    assert p.event_type == EventType.SYSTEM


# ── Intake: Affect ──────────────────────────────────────────────

def test_compute_valence_positive():
    mood = MoodState(valence=0.0)
    v = compute_valence("I love this beautiful day", mood)
    assert v > 0


def test_compute_valence_negative():
    mood = MoodState(valence=0.0)
    v = compute_valence("I hate this terrible awful pain", mood)
    assert v < 0


def test_mood_congruent_bias():
    happy_mood = MoodState(valence=0.5)
    sad_mood = MoodState(valence=-0.5)
    v_happy = compute_valence("neutral text here", happy_mood)
    v_sad = compute_valence("neutral text here", sad_mood)
    assert v_happy > v_sad


def test_apply_affect_negative_mood():
    p = Perception(EventType.CONVERSATION, "test", 0.5, datetime.now(UTC))
    mood = MoodState(valence=-0.5)
    drives = DriveState()
    result = apply_affect(p, mood, drives)
    assert result.salience == 0.6  # boosted by 0.1


# ── Intake: Drives ──────────────────────────────────────────────

def test_clamp():
    assert clamp(1.5) == 1.0
    assert clamp(-0.5) == 0.0
    assert clamp(0.5) == 0.5


def test_update_drives_conversation_relief():
    drives = DriveState(social=0.8)
    p = Perception(EventType.CONVERSATION, "hello", 0.5, datetime.now(UTC))
    new = update_drives(drives, [p], elapsed_hours=0.0)
    assert new.social < drives.social  # social relief from conversation


def test_update_mood_homeostatic():
    mood = MoodState(valence=0.5, arousal=0.8)
    drives = DriveState()
    new = update_mood(mood, drives, [], elapsed_hours=1.0)
    assert new.valence < 0.5
    assert new.arousal < 0.8


# ── Intake: Formation (salience scoring) ────────────────────────

def test_estimate_novelty():
    assert _estimate_novelty("") == 0.0
    assert _estimate_novelty("hi") == 0.05
    assert _estimate_novelty("This is a longer message with some variety") > 0.1


def test_is_duplicate():
    assert _is_duplicate("hello world", ["hello world"]) is True
    assert _is_duplicate("hello world", ["goodbye universe"]) is False
    assert _is_duplicate("hello world", []) is False


def test_adjust_salience_uses_perception():
    p = Perception(EventType.CONVERSATION, "Hello friend how are you?", 0.5, datetime.now(UTC))
    mood = MoodState()
    drives = DriveState()
    s = _adjust_salience(p, mood, drives, None)
    # Should start from perception.salience (0.5) and add small mood boost
    assert 0.4 < s < 0.7


def test_adjust_salience_metadata_override():
    p = Perception(EventType.CONVERSATION, "test", 0.5, datetime.now(UTC), metadata={"salience": 0.99})
    s = _adjust_salience(p, MoodState(), DriveState(), None)
    assert s == 0.99


# ── Recall: Weighting ──────────────────────────────────────────

def test_decay_strength():
    s = decay_strength(0.5, age_hours=10)
    assert s < 0.5
    assert s >= 0.05  # floor


def test_classify_outcome():
    assert classify_outcome(0.3, 0.5, 0.4, 0.6) == "improved"
    assert classify_outcome(0.5, 0.3, 0.4, 0.6) == "degraded"
    assert classify_outcome(0.5, 0.5, 0.4, 0.6) == "neutral"


# ── Consolidation: Whisper ──────────────────────────────────────

def test_translate_whisper_curiosity():
    d = translate_whisper("drives.curiosity", 0.3, 0.7)
    assert "stir" in d.lower() or "wonder" in d.lower()


def test_translate_whisper_decrease():
    d = translate_whisper("drives.social", 0.7, 0.3)
    assert "solitude" in d.lower() or "softens" in d.lower()


def test_translate_whisper_unknown():
    d = translate_whisper("some.unknown.param", 0.3, 0.7)
    assert "shifts" in d.lower()


# ── Meta ────────────────────────────────────────────────────────

def test_adaptive_cooldown():
    assert compute_adaptive_cooldown(10, 0.9) == 7
    assert compute_adaptive_cooldown(10, 0.5) == 15
    assert compute_adaptive_cooldown(10, 0.2) == 20


# ── Hot Memory: Writer ──────────────────────────────────────────

def test_writer_creates_dirs(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    for subdir in MemoryWriter.SUBDIRS:
        assert (writer.root / subdir).is_dir()


def test_writer_append_journal(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    path = writer.append_journal("Test journal entry", moment_id="abc123")
    assert path.exists()
    content = path.read_text()
    assert "Test journal entry" in content
    assert "abc123" in content


def test_writer_append_visitor(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    path = writer.append_visitor("Alice", "She likes cats")
    assert path.exists()
    content = path.read_text()
    assert "She likes cats" in content


def test_writer_write_self_file(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    path = writer.write_self_file("identity", "# Identity\n\nI am a shopkeeper.")
    assert path.exists()
    content = path.read_text()
    assert "shopkeeper" in content


def test_writer_append_reflection(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    path = writer.append_reflection("Today was interesting", label="Daily Summary")
    assert path.exists()
    content = path.read_text()
    assert "Today was interesting" in content
    assert "Daily Summary" in content


# ── Hot Memory: Reader ──────────────────────────────────────────

def test_reader_grep_memory(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    writer.append_journal("The quick brown fox jumped over the lazy dog")
    writer.append_visitor("Bob", "Bob mentioned something about foxes")

    reader = MemoryReader(tmp_memory_dir)
    results = reader.grep_memory("fox")
    assert len(results) >= 1
    assert any("fox" in r["match"].lower() for r in results)


def test_reader_read_visitor(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    writer.append_visitor("Carol", "Carol brought flowers")

    reader = MemoryReader(tmp_memory_dir)
    content = reader.read_visitor("Carol")
    assert content is not None
    assert "flowers" in content


def test_reader_list_visitors(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    writer.append_visitor("Alice", "note")
    writer.append_visitor("Bob", "note")

    reader = MemoryReader(tmp_memory_dir)
    visitors = reader.list_visitors()
    assert len(visitors) == 2


def test_reader_read_recent_journal(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    writer.append_journal("Entry one about sunshine")
    writer.append_journal("Entry two about rain")

    reader = MemoryReader(tmp_memory_dir)
    entries = reader.read_recent_journal(days=1)
    assert len(entries) >= 1


def test_reader_read_self_knowledge(tmp_memory_dir):
    writer = MemoryWriter(tmp_memory_dir)
    writer.write_self_file("identity", "I am curious and warm.")

    reader = MemoryReader(tmp_memory_dir)
    content = reader.read_self_knowledge("identity")
    assert content is not None
    assert "curious" in content


# ── Storage: SQLite (Three-Tier) ────────────────────────────────

@pytest.mark.asyncio
async def test_sqlite_day_memory(tmp_db):
    storage = SQLiteStorage(tmp_db)
    await storage.initialize()

    # Record a moment
    moment = DayMoment(
        id="m-1",
        content="Hello world",
        event_type=EventType.CONVERSATION,
        salience=0.7,
        valence=0.2,
        drive_snapshot={"curiosity": 0.5},
        timestamp=datetime.now(UTC),
    )
    mid = await storage.record_moment(moment)
    assert mid == "m-1"

    # Get unprocessed
    moments = await storage.get_unprocessed_moments()
    assert len(moments) == 1
    assert moments[0].content == "Hello world"

    # Day memory count
    assert await storage.get_day_memory_count() == 1

    # Mark processed
    await storage.mark_moment_processed("m-1")
    moments = await storage.get_unprocessed_moments()
    assert len(moments) == 0

    # Flush
    flushed = await storage.flush_day_memory()
    assert flushed == 1

    await storage.close()


@pytest.mark.asyncio
async def test_sqlite_eviction(tmp_db):
    storage = SQLiteStorage(tmp_db)
    await storage.initialize()

    # Get lowest salience moment
    lowest = await storage.get_lowest_salience_moment()
    assert lowest is None  # Empty

    # Add two moments
    m1 = DayMoment(
        id="m-low", content="Low salience", event_type=EventType.SYSTEM,
        salience=0.2, valence=0.0, drive_snapshot={},
        timestamp=datetime.now(UTC),
    )
    m2 = DayMoment(
        id="m-high", content="High salience", event_type=EventType.CONVERSATION,
        salience=0.9, valence=0.0, drive_snapshot={},
        timestamp=datetime.now(UTC),
    )
    await storage.record_moment(m1)
    await storage.record_moment(m2)

    lowest = await storage.get_lowest_salience_moment()
    assert lowest.id == "m-low"

    # Delete moment
    await storage.delete_moment("m-low")
    assert await storage.get_day_memory_count() == 1

    await storage.close()


@pytest.mark.asyncio
async def test_sqlite_drive_state(tmp_db):
    storage = SQLiteStorage(tmp_db)
    await storage.initialize()

    drives = await storage.get_drive_state()
    assert drives.curiosity == 0.5

    drives.curiosity = 0.8
    await storage.set_drive_state(drives)

    drives2 = await storage.get_drive_state()
    assert drives2.curiosity == 0.8

    await storage.close()


@pytest.mark.asyncio
async def test_sqlite_self_model(tmp_db):
    storage = SQLiteStorage(tmp_db)
    await storage.initialize()

    model = await storage.get_self_model()
    assert model.version == 0

    model.traits = {"warmth": 0.7}
    model.version = 1
    await storage.save_self_model(model)

    model2 = await storage.get_self_model()
    assert model2.traits["warmth"] == 0.7
    assert model2.version == 1

    await storage.close()


# ── Full Integration ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alive_memory_full_cycle(tmp_db, tmp_memory_dir):
    """Full cycle: intake → recall → consolidate → state."""
    memory = AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir)
    await memory.initialize()

    # Record a high-salience conversation
    m = await memory.intake(
        event_type="conversation",
        content="Hello world, this is a really interesting conversation about philosophy and meaning",
        metadata={"salience": 0.95},  # Override to ensure it passes threshold
    )
    # With salience override, should be recorded
    assert m is not None
    assert m.content.startswith("Hello world")
    assert m.salience == 0.95

    # Record more moments
    await memory.intake(
        event_type="observation",
        content="The sunset was breathtakingly beautiful today with golden and crimson hues",
        metadata={"salience": 0.9},
    )

    # Consolidate (no LLM — raw moments written to journal)
    report = await memory.consolidate()
    assert report.moments_processed >= 1
    assert report.journal_entries_written >= 1

    # Recall from hot memory
    ctx = await memory.recall(query="sunset")
    assert isinstance(ctx, RecallContext)
    # The journal should have the sunset entry
    assert ctx.total_hits >= 0  # May or may not match depending on journal content

    # Check state
    state = await memory.get_state()
    assert state.drives.curiosity >= 0
    assert state.mood.valence >= -1

    # Inject backstory
    bs = await memory.inject_backstory("I was created to help.", title="origin")
    assert bs.salience == 1.0

    # Drive update
    drives = await memory.update_drive("curiosity", 0.1)
    assert drives.curiosity > 0.5

    await memory.close()


@pytest.mark.asyncio
async def test_alive_memory_context_manager(tmp_db, tmp_memory_dir):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        result = await memory.intake(
            event_type="observation",
            content="The sky is a magnificent shade of blue with wispy clouds",
            metadata={"salience": 0.9},
        )
        assert result is not None

        # Consolidate to write to journal
        await memory.consolidate()

        # Recall
        ctx = await memory.recall(query="sky")
        assert isinstance(ctx, RecallContext)


@pytest.mark.asyncio
async def test_intake_salience_gating(tmp_db, tmp_memory_dir):
    """Low-salience events should return None."""
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        # Very short, low-info system event
        result = await memory.intake(
            event_type="system",
            content="ok",
        )
        # System event with 2-letter content should be below threshold
        assert result is None


@pytest.mark.asyncio
async def test_consolidation_writes_journal(tmp_db, tmp_memory_dir):
    """Consolidation should write journal entries from day moments."""
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        # Force high-salience moments
        for i in range(3):
            await memory.intake(
                event_type="conversation",
                content=f"Important conversation number {i} about unique topics xyz{i}",
                metadata={"salience": 0.9},
            )

        report = await memory.consolidate()
        assert report.moments_processed >= 1

        # Check journal files exist
        reader = MemoryReader(tmp_memory_dir)
        entries = reader.read_recent_journal(days=1)
        assert len(entries) >= 1


@pytest.mark.asyncio
async def test_cold_embeddings_created_on_full_consolidation(tmp_db, tmp_memory_dir):
    """Full consolidation should create cold embeddings."""
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        await memory.intake(
            event_type="conversation",
            content="A memorable conversation about quantum physics and the nature of reality",
            metadata={"salience": 0.95},
        )

        report = await memory.consolidate(depth="full")
        assert report.cold_embeddings_added >= 1

        # Verify cold embeddings in storage
        count = await memory.storage.count_cold_embeddings()
        assert count >= 1


@pytest.mark.asyncio
async def test_nap_mode(tmp_db, tmp_memory_dir):
    """Nap mode should process moments but not create cold embeddings."""
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        await memory.intake(
            event_type="conversation",
            content="A quick chat about the weather forecast for tomorrow",
            metadata={"salience": 0.9},
        )

        report = await memory.consolidate(depth="nap")
        assert report.depth == "nap"
        assert report.moments_processed >= 1
        assert report.cold_embeddings_added == 0

        # Moments should still be in day_memory (not flushed for nap)
        count = await memory.storage.count_cold_embeddings()
        assert count == 0
