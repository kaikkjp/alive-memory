"""Tests for the file watcher auto-ingestion."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from alive_memory import AliveMemory
from alive_memory.intake.file_watcher import FileWatcher, _is_media_file, _is_text_file


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_test_fw_mem_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_inbox():
    d = tempfile.mkdtemp(prefix="alive_test_inbox_")
    yield Path(d)
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ── Helpers ──────────────────────────────────────────────────────


def test_is_text_file():
    assert _is_text_file(Path("notes.txt"))
    assert _is_text_file(Path("readme.md"))
    assert _is_text_file(Path("data.json"))
    assert _is_text_file(Path("config.yaml"))
    assert not _is_text_file(Path("photo.jpg"))
    assert not _is_text_file(Path("song.mp3"))
    assert not _is_text_file(Path("unknown.xyz"))


def test_is_media_file():
    assert _is_media_file(Path("photo.jpg"))
    assert _is_media_file(Path("song.mp3"))
    assert _is_media_file(Path("clip.mp4"))
    assert _is_media_file(Path("doc.pdf"))
    assert not _is_media_file(Path("notes.txt"))
    assert not _is_media_file(Path("unknown.zzz"))


# ── FileWatcher lifecycle ────────────────────────────────────────


async def test_watcher_start_stop(tmp_db, tmp_memory_dir, tmp_inbox):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        watcher = FileWatcher(memory, watch_dir=tmp_inbox, poll_interval=0.1)
        assert not watcher.running

        await watcher.start()
        assert watcher.running

        await watcher.stop()
        assert not watcher.running


async def test_watcher_creates_watch_dir(tmp_db, tmp_memory_dir):
    nonexistent = Path(tempfile.mkdtemp()) / "sub" / "inbox"
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        watcher = FileWatcher(memory, watch_dir=nonexistent)
        await watcher.start()
        assert nonexistent.is_dir()
        await watcher.stop()
    import shutil
    shutil.rmtree(nonexistent.parent.parent, ignore_errors=True)


async def test_watcher_ignores_existing_files(tmp_db, tmp_memory_dir, tmp_inbox):
    # Create a file before starting
    (tmp_inbox / "old.txt").write_text("old content")

    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        watcher = FileWatcher(memory, watch_dir=tmp_inbox, poll_interval=0.1)
        await watcher.start()
        # Existing file should be in seen set
        assert watcher.seen_count == 1
        await watcher.stop()


async def test_watcher_ingests_new_text_file(tmp_db, tmp_memory_dir, tmp_inbox):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        watcher = FileWatcher(memory, watch_dir=tmp_inbox, poll_interval=0.1)
        await watcher.start()

        # Drop a text file
        (tmp_inbox / "note.txt").write_text(
            "Today I learned about quantum entanglement and its implications "
            "for faster-than-light communication theories."
        )

        # Wait for scan
        await asyncio.sleep(0.3)
        await watcher.stop()

        # File should now be seen
        assert watcher.seen_count >= 1


async def test_watcher_ingest_file_directly(tmp_db, tmp_memory_dir, tmp_inbox):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        watcher = FileWatcher(memory, watch_dir=tmp_inbox)

        # Directly ingest a text file
        path = tmp_inbox / "direct.txt"
        path.write_text("Direct ingestion test content with enough words to be interesting.")
        result = await watcher.ingest_file(path)
        assert result is True


async def test_watcher_skips_hidden_files(tmp_db, tmp_memory_dir, tmp_inbox):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        watcher = FileWatcher(memory, watch_dir=tmp_inbox, poll_interval=0.1)
        await watcher.start()

        # Drop a hidden file
        (tmp_inbox / ".hidden").write_text("should be ignored")
        await asyncio.sleep(0.3)
        await watcher.stop()


async def test_watcher_delete_after_ingest(tmp_db, tmp_memory_dir, tmp_inbox):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        watcher = FileWatcher(
            memory, watch_dir=tmp_inbox, poll_interval=0.1, delete_after_ingest=True,
        )
        await watcher.start()

        path = tmp_inbox / "ephemeral.txt"
        path.write_text("This file should be deleted after ingestion with enough content.")
        await asyncio.sleep(0.3)
        await watcher.stop()

        assert not path.exists()


async def test_watcher_skips_media_without_llm(tmp_db, tmp_memory_dir, tmp_inbox):
    """Media files are skipped when no multimodal LLM is available."""
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        watcher = FileWatcher(memory, watch_dir=tmp_inbox)

        path = tmp_inbox / "photo.jpg"
        path.write_bytes(b"fake image data")
        result = await watcher.ingest_file(path)
        assert result is False
