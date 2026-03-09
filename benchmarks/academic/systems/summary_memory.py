"""Rolling summary baseline.

Maintains a running LLM-generated summary of conversation history.
Constant storage, but loses detail progressively. High LLM cost
because every ingested conversation triggers a re-summarization.
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


class SummaryMemorySystem(MemorySystemAdapter):
    """Baseline: maintain a rolling summary of all conversations."""

    def __init__(self) -> None:
        self._summary = ""
        self._tracker = LLMTracker()
        self._pending_turns: list[str] = []
        self._summarize_every = 20  # batch turns before summarizing

    @property
    def system_id(self) -> str:
        return "summary"

    async def setup(self, config: dict) -> None:
        self._summary = ""
        self._tracker = LLMTracker()
        self._pending_turns = []
        self._summarize_every = config.get("summarize_every", 20)
        # Build llm_config with keys that llm_answer() expects
        self._llm_config: dict = {}
        if "llm_model" in config:
            self._llm_config["model"] = config["llm_model"]
        if "api_key" in config:
            self._llm_config["api_key"] = config["api_key"]

    async def add_conversation(self, turns: list[ConversationTurn]) -> None:
        for turn in turns:
            self._pending_turns.append(f"[{turn.role}]: {turn.content}")

        # Batch summarization to avoid per-turn LLM calls
        if len(self._pending_turns) >= self._summarize_every:
            await self._update_summary()

    async def _update_summary(self) -> None:
        """Re-summarize with pending turns."""
        if not self._pending_turns:
            return

        new_content = "\n".join(self._pending_turns)

        prompt = (
            f"You are maintaining a running summary of a conversation.\n\n"
            f"Current summary:\n{self._summary or '(empty)'}\n\n"
            f"New conversation turns:\n{new_content}\n\n"
            f"Write an updated summary that incorporates the new information. "
            f"Preserve key facts, names, dates, and decisions. "
            f"Keep the summary under 2000 words."
        )

        answer = await llm_answer(
            question=prompt,
            context="",
            llm_config=self._llm_config,
            tracker=self._tracker,
        )

        if not answer.startswith("[error"):
            self._summary = answer
            self._pending_turns = []
        # On failure, pending turns are preserved for the next attempt

    async def consolidate(self) -> None:
        """Flush any pending turns into the summary."""
        if self._pending_turns:
            await self._update_summary()

    async def answer_query(self, query: MemoryQuery, llm_config: dict) -> str:
        # Flush pending turns first
        if self._pending_turns:
            await self._update_summary()

        return await llm_answer(
            question=query.question,
            context=self._summary,
            llm_config=llm_config,
            tracker=self._tracker,
        )

    async def get_metrics(self) -> SystemMetrics:
        return SystemMetrics(
            total_llm_calls=self._tracker.total_calls,
            total_tokens=self._tracker.total_tokens,
            storage_bytes=sys.getsizeof(self._summary),
            memory_count=1 if self._summary else 0,
        )

    async def reset(self) -> None:
        self._summary = ""
        self._pending_turns = []
        self._tracker = LLMTracker()
