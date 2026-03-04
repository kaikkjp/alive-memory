"""Unit + integration tests for the wake phase module."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from alive_memory import AliveMemory
from alive_memory.consolidation.wake import WakeConfig, WakeHooks, run_wake_transition
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import DayMoment, EventType, WakeReport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_wake_test_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def _make_mock_hooks(
    threads: int = 3,
    pool: int = 5,
) -> AsyncMock:
    """Create mock hooks implementing the WakeHooks protocol."""
    hooks = AsyncMock()
    hooks.manage_threads = AsyncMock(return_value=threads)
    hooks.cleanup_pool = AsyncMock(return_value=pool)
    hooks.reset_drives = AsyncMock(return_value=None)
    hooks.update_self_files = AsyncMock(return_value=None)
    return hooks


# ---------------------------------------------------------------------------
# WakeConfig
# ---------------------------------------------------------------------------

def test_wake_config_defaults():
    cfg = WakeConfig()
    assert cfg.thread_dormant_hours == 48
    assert cfg.thread_archive_days == 7
    assert cfg.pool_max_unseen == 50
    assert cfg.stale_moment_hours == 72
    assert cfg.morning_defaults == {}
    assert cfg.preserve_fields == ["mood_valence"]


def test_wake_config_custom():
    cfg = WakeConfig(
        thread_dormant_hours=24,
        stale_moment_hours=48,
        morning_defaults={"energy": 0.7},
        preserve_fields=["mood_valence", "mood_arousal"],
    )
    assert cfg.thread_dormant_hours == 24
    assert cfg.stale_moment_hours == 48
    assert cfg.morning_defaults == {"energy": 0.7}
    assert "mood_arousal" in cfg.preserve_fields


# ---------------------------------------------------------------------------
# WakeHooks protocol
# ---------------------------------------------------------------------------

def test_wake_hooks_protocol():
    """AsyncMock satisfies the WakeHooks protocol."""
    hooks = _make_mock_hooks()
    assert isinstance(hooks, WakeHooks)


# ---------------------------------------------------------------------------
# run_wake_transition — with hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wake_transition_with_hooks():
    """Mock all 4 hooks, verify they're called in order, verify report counts."""
    hooks = _make_mock_hooks(threads=2, pool=4)
    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(return_value=1)
    storage.get_unprocessed_moments = AsyncMock(return_value=[])
    storage.flush_day_memory = AsyncMock(return_value=3)

    report = await run_wake_transition(storage, hooks=hooks)

    assert isinstance(report, WakeReport)
    assert report.threads_managed == 2
    assert report.pool_items_cleaned == 4
    assert report.stale_moments_flushed == 1
    assert report.day_memory_flushed == 3
    assert report.duration_ms >= 0

    # Verify hooks were called
    hooks.manage_threads.assert_awaited_once_with(48, 7)
    hooks.cleanup_pool.assert_awaited_once_with(50)
    hooks.reset_drives.assert_awaited_once_with({}, ["mood_valence"])
    hooks.update_self_files.assert_awaited_once()


# ---------------------------------------------------------------------------
# run_wake_transition — no hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wake_transition_no_hooks():
    """Run with hooks=None, verify SDK concerns (flush) still run."""
    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(return_value=5)
    storage.get_unprocessed_moments = AsyncMock(return_value=[])
    storage.flush_day_memory = AsyncMock(return_value=2)

    report = await run_wake_transition(storage)

    assert report.threads_managed == 0
    assert report.pool_items_cleaned == 0
    assert report.stale_moments_flushed == 5
    assert report.day_memory_flushed == 2


# ---------------------------------------------------------------------------
# Hook failure isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wake_transition_hook_failure():
    """One hook raises exception, others still run, no crash."""
    hooks = _make_mock_hooks()
    hooks.manage_threads = AsyncMock(side_effect=RuntimeError("thread fail"))

    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.get_unprocessed_moments = AsyncMock(return_value=[])
    storage.flush_day_memory = AsyncMock(return_value=0)

    report = await run_wake_transition(storage, hooks=hooks)

    # manage_threads failed — should be 0
    assert report.threads_managed == 0
    # Other hooks should still have been called
    hooks.cleanup_pool.assert_awaited_once()
    hooks.reset_drives.assert_awaited_once()
    hooks.update_self_files.assert_awaited_once()


# ---------------------------------------------------------------------------
# run_wake_transition — with embedder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wake_transition_with_embedder():
    """Verify cold embedding step runs when embedder provided."""
    storage = AsyncMock()
    moment = MagicMock()
    moment.content = "test content"
    moment.id = "m-1"
    moment.event_type = MagicMock()
    moment.event_type.value = "conversation"
    moment.valence = 0.5
    moment.salience = 0.8

    storage.get_unprocessed_moments = AsyncMock(return_value=[moment])
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.flush_day_memory = AsyncMock(return_value=0)
    storage.store_cold_embedding = AsyncMock(return_value="e-1")

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    report = await run_wake_transition(storage, embedder=embedder)

    assert report.cold_embeddings_added == 1
    embedder.embed.assert_awaited_once_with("test content")
    storage.store_cold_embedding.assert_awaited_once()


# ---------------------------------------------------------------------------
# Flush stale moments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wake_flush_stale_moments():
    """Verify stale moments are flushed based on stale_moment_hours."""
    storage = AsyncMock()
    storage.flush_stale_moments = AsyncMock(return_value=7)
    storage.get_unprocessed_moments = AsyncMock(return_value=[])
    storage.flush_day_memory = AsyncMock(return_value=0)

    cfg = WakeConfig(stale_moment_hours=24)
    report = await run_wake_transition(storage, config=cfg)

    assert report.stale_moments_flushed == 7
    storage.flush_stale_moments.assert_awaited_once_with(24)


# ---------------------------------------------------------------------------
# consolidate() with wake_hooks — integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consolidate_with_wake_hooks(tmp_db, tmp_memory_dir):
    """Full consolidate() with wake_hooks, verify wake phase runs after consolidation."""
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        await memory.intake(
            event_type="conversation",
            content="An important philosophical discussion about meaning and purpose",
            metadata={"salience": 0.95},
        )

        hooks = _make_mock_hooks()
        report = await memory.consolidate(wake_hooks=hooks)

        assert report.wake_report is not None
        assert isinstance(report.wake_report, WakeReport)
        hooks.manage_threads.assert_awaited_once()
        hooks.cleanup_pool.assert_awaited_once()
        hooks.reset_drives.assert_awaited_once()
        hooks.update_self_files.assert_awaited_once()


# ---------------------------------------------------------------------------
# Nap mode should NOT run wake even if hooks provided
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consolidate_nap_no_wake(tmp_db, tmp_memory_dir):
    """Nap mode should NOT run wake even if hooks provided."""
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        await memory.intake(
            event_type="conversation",
            content="Quick chat about the weather and seasons changing",
            metadata={"salience": 0.9},
        )

        hooks = _make_mock_hooks()
        report = await memory.consolidate(depth="nap", wake_hooks=hooks)

        assert report.wake_report is None
        hooks.manage_threads.assert_not_awaited()


# ---------------------------------------------------------------------------
# flush_stale_moments on real SQLiteStorage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_stale_moments_storage(tmp_db):
    """Test the new flush_stale_moments() method on SQLiteStorage directly."""
    storage = SQLiteStorage(tmp_db)
    await storage.initialize()

    # Insert a stale moment (100 hours old, unprocessed)
    stale_ts = datetime.now(UTC) - timedelta(hours=100)
    stale_moment = DayMoment(
        id="m-stale",
        content="Very old unprocessed moment",
        event_type=EventType.OBSERVATION,
        salience=0.5,
        valence=0.0,
        drive_snapshot={},
        timestamp=stale_ts,
    )
    await storage.record_moment(stale_moment)

    # Insert a recent moment (1 hour old, unprocessed)
    recent_ts = datetime.now(UTC) - timedelta(hours=1)
    recent_moment = DayMoment(
        id="m-recent",
        content="Recent unprocessed moment",
        event_type=EventType.CONVERSATION,
        salience=0.7,
        valence=0.3,
        drive_snapshot={},
        timestamp=recent_ts,
    )
    await storage.record_moment(recent_moment)

    # Flush stale (>72 hours)
    flushed = await storage.flush_stale_moments(stale_hours=72)
    assert flushed == 1

    # Verify only the recent moment remains
    remaining = await storage.get_unprocessed_moments()
    assert len(remaining) == 1
    assert remaining[0].id == "m-recent"

    await storage.close()
