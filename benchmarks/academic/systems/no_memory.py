"""No external memory baseline.

The model answers queries using only the question text — no conversation
history is available. This is the absolute floor for memory benchmarks.
"""

from __future__ import annotations

from benchmarks.academic.harness.base import (
    ConversationTurn,
    MemoryQuery,
    MemorySystemAdapter,
    SystemMetrics,
)
from benchmarks.academic.systems.llm_utils import LLMTracker, llm_answer


class NoMemorySystem(MemorySystemAdapter):
    """Baseline: answer with no conversation history at all."""

    def __init__(self) -> None:
        self._tracker = LLMTracker()

    @property
    def system_id(self) -> str:
        return "no-memory"

    async def setup(self, config: dict) -> None:
        self._tracker = LLMTracker()

    async def add_conversation(self, turns: list[ConversationTurn]) -> None:
        pass  # intentionally discards all history

    async def answer_query(self, query: MemoryQuery, llm_config: dict) -> str:
        return await llm_answer(
            question=query.question,
            context="",
            llm_config=llm_config,
            tracker=self._tracker,
        )

    async def get_metrics(self) -> SystemMetrics:
        return SystemMetrics(
            total_llm_calls=self._tracker.total_calls,
            total_tokens=self._tracker.total_tokens,
            storage_bytes=0,
            memory_count=0,
        )
