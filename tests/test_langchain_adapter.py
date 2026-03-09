"""Tests for the LangChain adapter (three-tier architecture)."""

from __future__ import annotations

import os
import tempfile

import pytest

from alive_memory import AliveMemory

# Import conditionally so tests are skipped if langchain not installed
langchain_core = pytest.importorskip("langchain_core")

from unittest.mock import AsyncMock, patch

from alive_memory.adapters.langchain import (
    AliveMessageHistory,
    AliveRetriever,
    _run_async,
)
from alive_memory.types import RecallContext
from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_lc_test_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def memory(tmp_db, tmp_memory_dir):
    mem = AliveMemory(storage=tmp_db, memory_dir=tmp_memory_dir)
    await mem.initialize()
    yield mem
    await mem.close()


# ── AliveMessageHistory ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_message_history_add_and_retrieve(memory):
    history = AliveMessageHistory(memory=memory)

    # Add messages with high salience to ensure they're recorded
    await history.aadd_messages([
        HumanMessage(content="What is the meaning of life and the universe and everything in it?"),
        AIMessage(content="42, according to Douglas Adams, from the Hitchhiker's Guide to the Galaxy."),
    ])

    # Consolidate to write to journal (hot memory)
    await memory.consolidate()

    # Retrieve — recall returns journal entries from hot memory
    messages = await history.aget_messages()
    assert len(messages) >= 1


@pytest.mark.asyncio
async def test_message_history_clear_raises(memory):
    history = AliveMessageHistory(memory=memory)
    with pytest.raises(NotImplementedError):
        history.clear()
    with pytest.raises(NotImplementedError):
        await history.aclear()


# ── AliveRetriever ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retriever_returns_documents(memory):
    # Add high-salience content and consolidate to get it into hot memory
    await memory.intake(
        event_type="conversation",
        content="Paris is the capital of France and has the Eiffel Tower",
        metadata={"salience": 0.95},
    )
    await memory.consolidate()

    retriever = AliveRetriever(memory=memory, recall_limit=5)
    docs = await retriever._aget_relevant_documents("Paris France")

    assert len(docs) >= 1
    assert any("Paris" in d.page_content for d in docs)


@pytest.mark.asyncio
async def test_retriever_document_metadata(memory):
    await memory.intake(
        event_type="observation",
        content="The sky is a brilliant shade of blue with wispy clouds overhead",
        metadata={"salience": 0.9},
    )
    await memory.consolidate()

    retriever = AliveRetriever(memory=memory)
    docs = await retriever._aget_relevant_documents("sky blue")

    assert len(docs) >= 1
    doc = docs[0]
    assert "source" in doc.metadata
    assert "query" in doc.metadata


# ── Sync wrappers ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_message_history_sync_add_message(memory):
    """Cover add_message (sync wrapper) and _run_async thread-pool branch."""
    history = AliveMessageHistory(memory=memory)
    # add_message calls _run_async from within a running loop → thread pool path
    history.add_message(
        HumanMessage(content="Sync wrapper test: exploring consciousness deeply")
    )


@pytest.mark.asyncio
async def test_message_history_sync_messages_property(memory):
    """Cover messages property (sync wrapper)."""
    history = AliveMessageHistory(memory=memory)
    msgs = history.messages
    assert isinstance(msgs, list)


@pytest.mark.asyncio
async def test_retriever_sync_get_relevant_documents(memory):
    """Cover _get_relevant_documents (sync wrapper)."""
    retriever = AliveRetriever(memory=memory, recall_limit=5)
    docs = retriever._get_relevant_documents("test query")
    assert isinstance(docs, list)


# ── Retriever with all recall fields populated ──────────────────


@pytest.mark.asyncio
async def test_retriever_converts_all_recall_fields(memory):
    """Cover visitor_notes, self_knowledge, and reflections loops."""
    retriever = AliveRetriever(memory=memory, recall_limit=20)

    mock_ctx = RecallContext(
        journal_entries=["journal entry about weather"],
        visitor_notes=["visitor Alice came by"],
        self_knowledge=["I am curious by nature"],
        reflections=["I noticed I enjoy helping others"],
        query="test",
        total_hits=4,
    )

    with patch.object(
        memory, "recall", new_callable=AsyncMock, return_value=mock_ctx
    ):
        docs = await retriever._aget_relevant_documents("test")

    assert len(docs) == 4
    sources = [d.metadata["source"] for d in docs]
    assert "journal" in sources
    assert "visitors" in sources
    assert "self" in sources
    assert "reflections" in sources


# ── _run_async without running loop ─────────────────────────────


def test_run_async_no_loop():
    """Cover _run_async when no event loop is running (asyncio.run branch)."""
    async def simple_coro():
        return 42

    result = _run_async(simple_coro())
    assert result == 42
