"""LangChain adapter for alive-memory.

Provides:
- AliveMessageHistory: Chat message history backed by alive-memory
- AliveRetriever: RAG retriever backed by alive-memory recall

Usage:
    from alive_memory import AliveMemory
    from alive_memory.adapters.langchain import AliveMessageHistory, AliveRetriever

    memory = AliveMemory(storage="memory.db", memory_dir="/data/agent/memory")
    await memory.initialize()

    history = AliveMessageHistory(memory=memory)
    retriever = AliveRetriever(memory=memory)
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field, PrivateAttr

from alive_memory import AliveMemory


def _run_async(coro):
    """Run an async coroutine from sync context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()


class AliveMessageHistory(BaseChatMessageHistory):
    """Chat message history backed by alive-memory.

    Stores messages via intake() and retrieves via recall().
    With the three-tier architecture, intake may return None for
    low-salience messages, and recall returns RecallContext
    with grep results from hot memory.
    """

    def __init__(self, *, memory: AliveMemory, recall_limit: int = 20) -> None:
        self._memory = memory
        self._recall_limit = recall_limit

    @property
    def messages(self) -> list[BaseMessage]:  # type: ignore[override]
        """Retrieve messages (sync wrapper)."""
        return _run_async(self.aget_messages())  # type: ignore[no-any-return]

    async def aget_messages(self) -> list[BaseMessage]:
        """Retrieve recent messages from alive-memory.

        Uses hot memory recall — returns journal entries and
        conversation context as messages.
        """
        ctx = await self._memory.recall(
            query="conversation history",
            limit=self._recall_limit,
        )
        result: list[BaseMessage] = []
        # Journal entries may include markdown headers from consolidation
        # (e.g., "## 01:16 [id]\n\n[role:ai] hello"). Search anywhere
        # in the entry for role tags, not just startswith().
        for entry in ctx.journal_entries:
            if "[role:ai] " in entry:
                # Extract content after the role tag
                idx = entry.index("[role:ai] ")
                content = entry[idx + len("[role:ai] "):]
                result.append(AIMessage(content=content))
            elif "[role:human] " in entry:
                idx = entry.index("[role:human] ")
                content = entry[idx + len("[role:human] "):]
                result.append(HumanMessage(content=content))
            else:
                result.append(HumanMessage(content=entry))
        return result

    def add_message(self, message: BaseMessage) -> None:
        """Add a message (sync wrapper)."""
        _run_async(self.aadd_messages([message]))

    async def aadd_messages(self, messages: Sequence[BaseMessage]) -> None:
        """Store messages as moments via intake."""
        for msg in messages:
            role = "ai" if isinstance(msg, AIMessage) else "human"
            # Prefix content with role so it survives hot memory roundtrip
            tagged = f"[role:{role}] {msg.content}"
            await self._memory.intake(
                event_type="conversation",
                content=tagged,
                metadata={"role": role},
            )

    def clear(self) -> None:
        """Not supported — alive-memory has no bulk-delete by design."""
        raise NotImplementedError(
            "alive-memory does not support bulk-deleting memories. "
            "Memories decay naturally through consolidation."
        )

    async def aclear(self) -> None:
        """Not supported — alive-memory has no bulk-delete by design."""
        raise NotImplementedError(
            "alive-memory does not support bulk-deleting memories. "
            "Memories decay naturally through consolidation."
        )


class AliveRetriever(BaseRetriever):
    """RAG retriever backed by alive-memory recall.

    Converts RecallContext into LangChain Documents.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _memory: AliveMemory = PrivateAttr()
    recall_limit: int = Field(default=10)

    def __init__(self, *, memory: AliveMemory, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._memory = memory

    def _get_relevant_documents(self, query: str, **kwargs: Any) -> list[Document]:
        """Retrieve documents (sync wrapper)."""
        return _run_async(self._aget_relevant_documents(query, **kwargs))  # type: ignore[no-any-return]

    async def _aget_relevant_documents(
        self, query: str, **kwargs: Any
    ) -> list[Document]:
        """Retrieve memories as Documents from hot memory."""
        ctx = await self._memory.recall(
            query=query,
            limit=self.recall_limit,
        )

        docs: list[Document] = []

        # Journal entries
        for entry in ctx.journal_entries:
            docs.append(Document(
                page_content=entry,
                metadata={"source": "journal", "query": ctx.query},
            ))

        # Visitor notes
        for note in ctx.visitor_notes:
            docs.append(Document(
                page_content=note,
                metadata={"source": "visitors", "query": ctx.query},
            ))

        # Self-knowledge
        for knowledge in ctx.self_knowledge:
            docs.append(Document(
                page_content=knowledge,
                metadata={"source": "self", "query": ctx.query},
            ))

        # Reflections
        for reflection in ctx.reflections:
            docs.append(Document(
                page_content=reflection,
                metadata={"source": "reflections", "query": ctx.query},
            ))

        return docs[:self.recall_limit]
