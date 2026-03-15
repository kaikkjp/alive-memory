"""LangChain ConversationBufferMemory adapter.

Stores last N messages in a list. Perfect short-term recall,
catastrophic cliff when buffer is full. Zero LLM cost.
"""

import sys

from benchmarks.adapters.base import (
    BenchEvent,
    MemoryAdapter,
    RecallResult,
    SystemStats,
)

try:
    from langchain.memory import ConversationBufferWindowMemory
    from langchain_core.messages import AIMessage, HumanMessage
except ImportError:
    ConversationBufferWindowMemory = None  # type: ignore[assignment, misc]


class LangChainBufferAdapter(MemoryAdapter):
    """LangChain ConversationBufferWindowMemory wrapper.

    Uses recommended default config with k=10 (last 10 conversation turns).
    """

    def __init__(self) -> None:
        self._memory = None
        self._all_events: list[BenchEvent] = []  # track everything for stats
        self._k = 10

    async def setup(self, config: dict) -> None:
        if ConversationBufferWindowMemory is None:
            raise ImportError("langchain required: pip install langchain")

        self._k = config.get("k", 10)
        self._memory = ConversationBufferWindowMemory(
            k=self._k, return_messages=True
        )
        self._all_events = []

    async def ingest(self, event: BenchEvent) -> None:
        self._all_events.append(event)

        # Buffer only stores conversations as message pairs
        if event.event_type == "conversation":
            # Parse "User X: message" format
            content = event.content
            self._memory.chat_memory.add_message(HumanMessage(content=content))
        elif event.event_type in ("observation", "action"):
            # Store as AI messages (observations/actions the agent took)
            self._memory.chat_memory.add_message(AIMessage(content=event.content))

    async def recall(self, query: str, limit: int = 5) -> list[RecallResult]:
        if not self._memory:
            return []

        # Buffer memory doesn't do retrieval — it returns the last K messages.
        # For fairness, we search the buffer for query-relevant messages.
        messages = self._memory.chat_memory.messages
        query_lower = query.lower()
        query_words = [w for w in query_lower.split() if len(w) > 3]

        results = []
        for msg in reversed(messages):  # most recent first
            content = msg.content
            content_lower = content.lower()
            # Check if any query word appears in the message
            if any(w in content_lower for w in query_words):
                results.append(RecallResult(
                    content=content,
                    score=1.0,
                    metadata={"type": msg.type},
                    formed_at=None,
                ))
                if len(results) >= limit:
                    break

        # If keyword search found nothing, return most recent messages
        if not results:
            for msg in reversed(messages[-limit:]):
                results.append(RecallResult(
                    content=msg.content,
                    score=1.0,
                    metadata={"type": msg.type},
                    formed_at=None,
                ))

        return results[:limit]

    async def get_stats(self) -> SystemStats:
        msg_count = len(self._memory.chat_memory.messages) if self._memory else 0
        # Estimate storage from message content
        storage = sum(
            sys.getsizeof(m.content)
            for m in (self._memory.chat_memory.messages if self._memory else [])
        )
        return SystemStats(
            memory_count=msg_count,
            storage_bytes=storage,
            total_llm_calls=0,
            total_tokens=0,
        )

    async def teardown(self) -> None:
        self._memory = None
        self._all_events = []
