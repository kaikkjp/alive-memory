"""Integration tests for the sleep cycle orchestrator."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.sleep import SleepConfig, nap, sleep_cycle
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import DayMoment, EventType, SleepCycleReport


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_test_sleep_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def storage(tmp_db):
    s = SQLiteStorage(tmp_db)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def writer(tmp_memory_dir):
    return MemoryWriter(tmp_memory_dir)


@pytest.fixture
def reader(tmp_memory_dir):
    return MemoryReader(tmp_memory_dir)


# ── Test 1: Minimal sleep_cycle ──────────────────────────────────


@pytest.mark.asyncio
async def test_sleep_cycle_minimal(storage, writer, reader):
    """Call sleep_cycle() with only required params. Should run consolidation only."""
    report = await sleep_cycle(
        storage, writer, reader, llm=None,
    )
    assert isinstance(report, SleepCycleReport)
    assert "consolidation" in report.phases_completed
    assert report.depth == "full"
    assert report.errors == []


# ── Test 2: sleep_cycle with moments ─────────────────────────────


@pytest.mark.asyncio
async def test_sleep_cycle_with_moments(storage, writer, reader):
    """Insert moments, run sleep_cycle, assert consolidation processes them."""
    for i in range(3):
        moment = DayMoment(
            id=f"m-{i}",
            content=f"Interesting conversation number {i} about topic xyz{i}",
            event_type=EventType.CONVERSATION,
            salience=0.9,
            valence=0.1,
            drive_snapshot={"curiosity": 0.5},
            timestamp=datetime.now(UTC),
        )
        await storage.record_moment(moment)

    report = await sleep_cycle(storage, writer, reader, llm=None)
    assert report.moments_consolidated == 3
    assert "consolidation" in report.phases_completed
    assert report.journal_entries_written >= 3


# ── Test 3: sleep_cycle with whispers ────────────────────────────


@pytest.mark.asyncio
async def test_sleep_cycle_with_whispers(storage, writer, reader):
    """Pass whispers list, assert whisper phase ran and dreams generated."""
    whispers = [
        {"param_path": "drives.curiosity", "old_value": 0.3, "new_value": 0.7},
        {"param_path": "drives.social", "old_value": 0.5, "new_value": 0.3},
    ]
    report = await sleep_cycle(
        storage, writer, reader, llm=None,
        whispers=whispers,
    )
    assert "whisper" in report.phases_completed
    assert report.dreams_generated >= 2


# ── Test 4: nap variant ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_nap_variant(storage, writer, reader):
    """Call nap(), assert only consolidation runs with nap depth."""
    # Add a moment so consolidation has something to process
    moment = DayMoment(
        id="nap-1",
        content="A quick observation about the weather today being sunny",
        event_type=EventType.OBSERVATION,
        salience=0.8,
        valence=0.0,
        drive_snapshot={"curiosity": 0.5},
        timestamp=datetime.now(UTC),
    )
    await storage.record_moment(moment)

    report = await nap(storage, writer, reader, llm=None)
    assert report.depth == "nap"
    assert "consolidation" in report.phases_completed
    # Nap should not run meta, identity, or wake
    assert "meta_review" not in report.phases_completed
    assert "meta_controller" not in report.phases_completed
    assert "drift_detection" not in report.phases_completed
    assert "wake" not in report.phases_completed
    assert report.wake_completed is False


# ── Test 5: Fault tolerance continues ────────────────────────────


@pytest.mark.asyncio
async def test_fault_tolerance_continues(storage, writer, reader):
    """Mock consolidation to raise, assert remaining phases still run."""
    with patch(
        "alive_memory.consolidation.consolidate",
        new_callable=AsyncMock,
        side_effect=RuntimeError("consolidation exploded"),
    ):
        report = await sleep_cycle(
            storage, writer, reader, llm=None,
            sleep_config=SleepConfig(fault_tolerant=True),
        )
    assert "consolidation" not in report.phases_completed
    assert len(report.errors) >= 1
    assert "consolidation exploded" in report.errors[0]
    # Identity phase should still have run (drift detection)
    assert "drift_detection" in report.phases_completed


# ── Test 6: Fault tolerance disabled raises ──────────────────────


@pytest.mark.asyncio
async def test_fault_tolerance_disabled_raises(storage, writer, reader):
    """Set fault_tolerant=False, mock a phase to raise, assert propagates."""
    with (
        patch(
            "alive_memory.consolidation.consolidate",
            new_callable=AsyncMock,
            side_effect=RuntimeError("consolidation exploded"),
        ),
        pytest.raises(RuntimeError, match="consolidation exploded"),
    ):
        await sleep_cycle(
            storage, writer, reader, llm=None,
            sleep_config=SleepConfig(fault_tolerant=False),
        )


# ── Test 7: Identity phase with drift ───────────────────────────


@pytest.mark.asyncio
async def test_sleep_cycle_identity_phase(storage, writer, reader):
    """Insert traits with drift, assert drift_detected and evolution_decisions populated."""
    model = await storage.get_self_model()
    model.traits = {"warmth": 0.8, "curiosity": 0.6}
    # Simulate drift history with consistent increase
    model.drift_history = [
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": 0.1},
    ]
    model.version = 1
    await storage.save_self_model(model)

    report = await sleep_cycle(
        storage, writer, reader, llm=None,
        sleep_config=SleepConfig(enable_identity_evolution=True),
    )
    assert "drift_detection" in report.phases_completed
    assert report.drift_detected is True
    assert len(report.evolution_decisions) >= 1


# ── Test 8: Duration tracking ────────────────────────────────────


@pytest.mark.asyncio
async def test_sleep_report_duration(storage, writer, reader):
    """Assert duration_seconds > 0 after any sleep_cycle() call."""
    report = await sleep_cycle(storage, writer, reader, llm=None)
    assert report.duration_seconds > 0
