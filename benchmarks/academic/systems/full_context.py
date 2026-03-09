"""Full-context baseline.

Passes the entire conversation history into the LLM context window.
This is the theoretical upper bound for any memory system — but fails
when history exceeds the model's context limit.
"""

from __future__ import annotations

import sys

from benchmarks.academic.harness.base import (
    ConversationTurn,
    MemoryQuery,
    MemorySystemAdapter,
    SystemMetrics,
)
from benchmarks.academic.systems.llm_utils import LLMTracker, llm_answer


class FullContextSystem(MemorySystemAdapter):
    """Baseline: stuff all history into the prompt."""

    def __init__(self, max_context_chars: int = 200_000) -> None:
        self._history: list[str] = []
        self._tracker = LLMTracker()
        self._max_context_chars = max_context_chars

    @property
    def system_id(self) -> str:
        return "full-context"

    async def setup(self, config: dict) -> None:
        self._history = []
        self._tracker = LLMTracker()
        self._max_context_chars = config.get("max_context_chars", 200_000)

    async def add_conversation(self, turns: list[ConversationTurn]) -> None:
        for turn in turns:
            self._history.append(f"[{turn.role}]: {turn.content}")

    async def answer_query(self, query: MemoryQuery, llm_config: dict) -> str:
        # Join all history, truncating from the start if too long
        full = "\n".join(self._history)
        if len(full) > self._max_context_chars:
            full = full[-self._max_context_chars:]

        return await llm_answer(
            question=query.question,
            context=full,
            llm_config=llm_config,
            tracker=self._tracker,
        )

    async def get_metrics(self) -> SystemMetrics:
        storage = sum(sys.getsizeof(h) for h in self._history)
        return SystemMetrics(
            total_llm_calls=self._tracker.total_calls,
            total_tokens=self._tracker.total_tokens,
            storage_bytes=storage,
            memory_count=len(self._history),
        )

    async def reset(self) -> None:
        self._history = []
