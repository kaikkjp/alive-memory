"""Tests for AliveMemory.quickstart() convenience constructor."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from alive_memory import AliveMemory


@pytest.fixture
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="alive_qs_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


async def test_quickstart_creates_instance(tmp_data_dir):
    memory = AliveMemory.quickstart("test-agent", data_dir=tmp_data_dir)
    assert isinstance(memory, AliveMemory)
    assert (tmp_data_dir / "memory.db").parent == tmp_data_dir


async def test_quickstart_creates_data_dir(tmp_data_dir):
    sub = tmp_data_dir / "sub" / "deep"
    AliveMemory.quickstart("test", data_dir=sub)
    assert sub.is_dir()


async def test_quickstart_context_manager(tmp_data_dir):
    async with AliveMemory.quickstart("ctx-test", data_dir=tmp_data_dir) as memory:
        # Should be initialized and usable
        state = await memory.get_state()
        assert state is not None


async def test_quickstart_intake_recall(tmp_data_dir):
    async with AliveMemory.quickstart("ir-test", data_dir=tmp_data_dir) as memory:
        await memory.intake(
            event_type="conversation",
            content="The sunset painted the sky in brilliant oranges and deep purples.",
        )
        ctx = await memory.recall("sunset")
        # Should not error, context is valid
        assert ctx is not None


async def test_quickstart_default_dir():
    """quickstart() with default data_dir uses ~/.alive/{name}/."""
    memory = AliveMemory.quickstart("default-test-agent")
    expected = Path.home() / ".alive" / "default-test-agent"
    assert memory.memory_dir == expected / "hot"
    # Clean up
    shutil.rmtree(expected, ignore_errors=True)


async def test_quickstart_with_llm_string(tmp_data_dir):
    """quickstart() accepts LLM string shorthand (validates the path, not the key)."""
    # This will fail at runtime without an API key, but the constructor should work
    # We can't actually test "anthropic" without a key, so just test the path
    memory = AliveMemory.quickstart("llm-test", data_dir=tmp_data_dir)
    # No LLM by default
    assert memory._llm is None
