"""Tests for the LangChain adapter (three-tier architecture)."""

from __future__ import annotations

import os
import tempfile

import pytest

from alive_memory import AliveMemory

# Import conditionally so tests are skipped if langchain not installed
langchain_core = pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from alive_memory.adapters.langchain import AliveMessageHistory, AliveRetriever  # noqa: E402


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
