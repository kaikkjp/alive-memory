"""Integration tests for the alive-memory SDK."""

import asyncio
import os
import tempfile

import pytest

from alive_memory import AliveMemory
from alive_memory.config import AliveConfig
from alive_memory.intake.thalamus import perceive
from alive_memory.intake.affect import compute_valence, apply_affect
from alive_memory.intake.drives import update_drives, update_mood, clamp
from alive_memory.consolidation.whisper import translate_whisper
from alive_memory.recall.weighting import score_memory, decay_strength
from alive_memory.identity.drift import DriftReport
from alive_memory.meta.controller import classify_outcome, compute_adaptive_cooldown
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import (
    CognitiveState, DriveState, EventType, Memory, MemoryType,
    MoodState, Perception, SelfModel,
)
from datetime import datetime, timezone


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


# ── Config ──────────────────────────────────────────────────────

def test_config_defaults():
    cfg = AliveConfig()
    assert cfg.get("memory.default_strength") == 0.5
    assert cfg.get("recall.default_limit") == 5
    assert cfg.get("nonexistent", 42) == 42


def test_config_dict_override():
    cfg = AliveConfig({"memory": {"default_strength": 0.9}})
    assert cfg.get("memory.default_strength") == 0.9
    assert cfg.get("memory.min_strength") == 0.05  # default still there


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
    p = Perception(EventType.CONVERSATION, "test", 0.5, datetime.now(timezone.utc))
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
    p = Perception(EventType.CONVERSATION, "hello", 0.5, datetime.now(timezone.utc))
    new = update_drives(drives, [p], elapsed_hours=0.0)
    assert new.social < drives.social  # social relief from conversation


def test_update_mood_homeostatic():
    mood = MoodState(valence=0.5, arousal=0.8)
    drives = DriveState()
    new = update_mood(mood, drives, [], elapsed_hours=1.0)
    # Should pull toward neutral
    assert new.valence < 0.5
    assert new.arousal < 0.8


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


# ── Storage: SQLite ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sqlite_lifecycle(tmp_db):
    storage = SQLiteStorage(tmp_db)
    await storage.initialize()

    # Store and retrieve a memory
    mem = Memory(
        id="test-1",
        content="Hello world",
        memory_type=MemoryType.EPISODIC,
        strength=0.7,
        valence=0.2,
        formed_at=datetime.now(timezone.utc),
    )
    mid = await storage.store_memory(mem)
    assert mid == "test-1"

    got = await storage.get_memory("test-1")
    assert got is not None
    assert got.content == "Hello world"
    assert got.strength == 0.7

    # Count
    assert await storage.count_memories() == 1

    # Update strength
    await storage.update_memory_strength("test-1", 0.9)
    got = await storage.get_memory("test-1")
    assert got.strength == 0.9

    # Update recall
    await storage.update_memory_recall("test-1")
    got = await storage.get_memory("test-1")
    assert got.recall_count == 1
    assert got.last_recalled is not None

    # Delete
    await storage.delete_memory("test-1")
    assert await storage.count_memories() == 0

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
async def test_alive_memory_full_cycle(tmp_db):
    """The 'What Success Looks Like' test from the task spec."""
    memory = AliveMemory(storage=tmp_db)
    await memory.initialize()

    # Record something
    m = await memory.intake(event_type="conversation", content="Hello world")
    assert m.content == "Hello world"
    assert m.strength > 0

    # Remember it
    results = await memory.recall(query="greetings", limit=3)
    assert len(results) > 0
    assert results[0].content == "Hello world"

    # Consolidate (no LLM — dreaming/reflection skipped)
    report = await memory.consolidate()
    assert report.memories_strengthened >= 0

    # Check state
    state = await memory.get_state()
    assert state.drives.curiosity >= 0
    assert state.mood.valence >= -1

    # Inject backstory
    bs = await memory.inject_backstory("I was created to help.")
    assert bs.strength == 0.9

    # Drive update
    drives = await memory.update_drive("curiosity", 0.1)
    assert drives.curiosity > 0.5

    await memory.close()


@pytest.mark.asyncio
async def test_alive_memory_context_manager(tmp_db):
    async with AliveMemory(storage=tmp_db) as memory:
        await memory.intake(event_type="observation", content="The sky is blue")
        results = await memory.recall(query="sky")
        assert len(results) == 1
