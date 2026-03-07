"""Tests for generic tool definitions, ADK adapter, and execute_tool."""

from __future__ import annotations

import os
import tempfile

import pytest

from alive_memory import AliveMemory
from alive_memory.adapters.tools import TOOL_DEFINITIONS, execute_tool


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_test_tools_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ── Tool Definitions ─────────────────────────────────────────────


def test_tool_definitions_structure():
    assert len(TOOL_DEFINITIONS) == 4
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {"memory_intake", "memory_recall", "memory_state", "memory_consolidate"}

    for tool in TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert "parameters" in tool
        assert tool["parameters"]["type"] == "object"


# ── execute_tool ─────────────────────────────────────────────────


async def test_execute_tool_intake(tmp_db, tmp_memory_dir):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        result = await execute_tool(memory, "memory_intake", {
            "event_type": "conversation",
            "content": "The weather is beautiful today, the sky is bright blue with fluffy clouds.",
        })
        assert isinstance(result, dict)
        assert "recorded" in result


async def test_execute_tool_recall(tmp_db, tmp_memory_dir):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        result = await execute_tool(memory, "memory_recall", {"query": "weather"})
        assert isinstance(result, dict)
        assert "total_hits" in result
        assert "journal_entries" in result


async def test_execute_tool_state(tmp_db, tmp_memory_dir):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        result = await execute_tool(memory, "memory_state", {})
        assert "mood" in result
        assert "drives" in result
        assert "energy" in result


async def test_execute_tool_consolidate(tmp_db, tmp_memory_dir):
    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        result = await execute_tool(memory, "memory_consolidate", {"depth": "nap"})
        assert "moments_processed" in result
        assert result["depth"] == "nap"


async def test_execute_tool_unknown():
    async with AliveMemory(storage=":memory:") as memory:
        with pytest.raises(ValueError, match="Unknown tool"):
            await execute_tool(memory, "nonexistent", {})


# ── ADK adapter ──────────────────────────────────────────────────


async def test_adk_create_tools(tmp_db, tmp_memory_dir):
    from alive_memory.adapters.adk import create_adk_tools

    async with AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir) as memory:
        tools = create_adk_tools(memory)
        assert len(tools) == 4
        # All should be async callables
        for tool in tools:
            assert callable(tool)
            assert tool.__name__.startswith("memory_")

        # Test the state tool actually works
        state_tool = next(t for t in tools if t.__name__ == "memory_state")
        result = await state_tool()
        assert "mood" in result
        assert "drives" in result
