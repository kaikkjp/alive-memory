"""LangChain ConversationSummaryMemory adapter.

LLM summarizes old conversations into a running summary.
Constant storage, but loses detail progressively. High LLM cost.
"""

import os
import sys

from benchmarks.adapters.base import (
    BenchEvent,
    MemoryAdapter,
    RecallResult,
    SystemStats,
)

try:
    from langchain.memory import ConversationSummaryMemory
except ImportError:
    ConversationSummaryMemory = None  # type: ignore[assignment, misc]

# Try LLM providers: prefer OpenRouter (OpenAI-compat), fall back to Anthropic
_llm_cls = None
_llm_kwargs: dict = {}

try:
    from langchain_openai import ChatOpenAI as _ChatOpenAI
    _llm_cls = _ChatOpenAI
except ImportError:
    pass

if _llm_cls is None:
    try:
        from langchain_anthropic import ChatAnthropic as _ChatAnthropic
        _llm_cls = _ChatAnthropic
    except ImportError:
        pass


class _TokenTracker:
    """Track LLM usage from LangChain callbacks."""

    def __init__(self) -> None:
        self.total_calls = 0
        self.total_tokens = 0


class LangChainSummaryAdapter(MemoryAdapter):
    """LangChain ConversationSummaryMemory wrapper.

    Uses Claude Haiku via OpenRouter (or Anthropic as fallback) for summarization.
    """

    def __init__(self) -> None:
        self._memory = None
        self._tracker = _TokenTracker()
        self._event_count = 0

    async def setup(self, config: dict) -> None:
        if ConversationSummaryMemory is None:
            raise ImportError(
                "langchain required: pip install langchain langchain-openai"
            )
        if _llm_cls is None:
            raise ImportError(
                "langchain LLM provider required: pip install langchain-openai"
            )

        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

        if openrouter_key and _llm_cls.__name__ == "ChatOpenAI":
            model = config.get("llm_model", "anthropic/claude-haiku-4-5")
            llm = _llm_cls(
                model=model,
                temperature=0,
                openai_api_key=openrouter_key,
                openai_api_base="https://openrouter.ai/api/v1",
            )
        elif anthropic_key:
            model = config.get("llm_model", "claude-haiku-4-5-20251001")
            llm = _llm_cls(model=model, temperature=0)
        else:
            raise RuntimeError(
                "No LLM API key found. Set OPENROUTER_API_KEY or ANTHROPIC_API_KEY."
            )

        self._memory = ConversationSummaryMemory(
            llm=llm, return_messages=False
        )
        self._tracker = _TokenTracker()
        self._event_count = 0

    async def ingest(self, event: BenchEvent) -> None:
        self._event_count += 1

        # Feed conversation events to the summary memory
        if event.event_type == "conversation":
            self._memory.save_context(
                {"input": event.content},
                {"output": f"[Processed event at cycle {event.cycle}]"},
            )
            self._tracker.total_calls += 1
            # Rough token estimate for the summarization call
            self._tracker.total_tokens += len(event.content) // 4 + 200
        elif event.event_type in ("observation", "action"):
            # Observations and actions also go through summary
            self._memory.save_context(
                {"input": f"[{event.event_type}] {event.content}"},
                {"output": "[noted]"},
            )
            self._tracker.total_calls += 1
            self._tracker.total_tokens += len(event.content) // 4 + 200

    async def recall(self, query: str, limit: int = 5) -> list[RecallResult]:
        if not self._memory:
            return []

        # Summary memory returns a single running summary
        variables = self._memory.load_memory_variables({})
        summary = variables.get("history", "")

        if not summary:
            return []

        # Return the summary as a single result
        return [RecallResult(
            content=summary,
            score=1.0,
            metadata={"type": "summary"},
            formed_at=None,
        )]

    async def get_stats(self) -> SystemStats:
        summary = ""
        if self._memory:
            variables = self._memory.load_memory_variables({})
            summary = variables.get("history", "")

        return SystemStats(
            memory_count=1 if summary else 0,  # one running summary
            storage_bytes=sys.getsizeof(summary),
            total_llm_calls=self._tracker.total_calls,
            total_tokens=self._tracker.total_tokens,
        )

    async def teardown(self) -> None:
        self._memory = None
