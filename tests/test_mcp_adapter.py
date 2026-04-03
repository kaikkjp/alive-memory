"""Tests for the MCP adapter."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from alive_memory import AliveMemory

mcp = pytest.importorskip("mcp", reason="mcp not installed")

import alive_memory.adapters.mcp as mcp_mod  # noqa: E402
from alive_memory.adapters.mcp import (  # noqa: E402
    _get_memory,
    memory_consolidate,
    memory_intake,
    memory_recall,
    memory_state,
)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_test_mcp_")
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def mcp_memory(tmp_db, tmp_memory_dir, monkeypatch):
    """Set up a fresh AliveMemory instance for the MCP module."""
    monkeypatch.setenv("ALIVE_DB", tmp_db)
    monkeypatch.setenv("ALIVE_MEMORY_DIR", tmp_memory_dir)
    # Reset the module-level singleton so _get_memory re-initializes
    mcp_mod._memory = None
    memory = await _get_memory()
    yield memory
    await memory.close()
    mcp_mod._memory = None


async def test_mcp_get_memory_lazy_init(tmp_db, tmp_memory_dir, monkeypatch):
    """_get_memory lazily initializes from env vars."""
    monkeypatch.setenv("ALIVE_DB", tmp_db)
    monkeypatch.setenv("ALIVE_MEMORY_DIR", tmp_memory_dir)
    mcp_mod._memory = None
    try:
        mem = await _get_memory()
        assert isinstance(mem, AliveMemory)
        # Second call returns the same instance
        mem2 = await _get_memory()
        assert mem is mem2
    finally:
        await mem.close()
        mcp_mod._memory = None


async def test_mcp_memory_intake(mcp_memory):
    result = json.loads(
        await memory_intake(
            event_type="conversation",
            content="The weather is beautiful today, the sky is bright blue.",
        )
    )
    assert isinstance(result, dict)
    assert "recorded" in result


async def test_mcp_memory_recall(mcp_memory):
    result = json.loads(await memory_recall(query="weather"))
    assert "total_hits" in result
    assert "journal_entries" in result


async def test_mcp_memory_state(mcp_memory):
    result = json.loads(await memory_state())
    assert "mood" in result
    assert "drives" in result
    assert "energy" in result


async def test_mcp_memory_consolidate(mcp_memory):
    result = json.loads(await memory_consolidate(depth="nap"))
    assert "moments_processed" in result
    assert result["depth"] == "nap"


def test_mcp_server_has_tools():
    """The FastMCP server instance should have our 4 tools registered."""
    from alive_memory.adapters.mcp import mcp as server

    assert server.name == "alive-memory"
