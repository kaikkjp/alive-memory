"""alive-memory system adapter for academic benchmarks.

Maps conversation turns to alive's intake/recall/consolidate API
and uses recalled context to answer queries.
"""

from __future__ import annotations

import os
import tempfile

from alive_memory import AliveMemory, EventType
from benchmarks.academic.harness.base import (
    ConversationTurn,
    MemoryQuery,
    MemorySystemAdapter,
    SystemMetrics,
)
from benchmarks.academic.systems.llm_utils import LLMTracker, llm_answer

_ROLE_TO_EVENT = {
    "user": EventType.CONVERSATION,
    "human": EventType.CONVERSATION,
    "assistant": EventType.CONVERSATION,
    "ai": EventType.CONVERSATION,
    "system": EventType.SYSTEM,
    "observation": EventType.OBSERVATION,
    "action": EventType.ACTION,
}


class AliveMemorySystem(MemorySystemAdapter):
    """alive-memory three-tier cognitive memory system."""

    def __init__(self) -> None:
        self._memory: AliveMemory | None = None
        self._tmp_dir: str | None = None
        self._db_path: str | None = None
        self._tracker = LLMTracker()
        self._llm_calls = 0
        self._llm_tokens = 0
        self._turn_count = 0

    @property
    def system_id(self) -> str:
        return "alive"

    async def setup(self, config: dict) -> None:
        self._setup_config = config  # preserve for reset() re-initialization
        self._tmp_dir = tempfile.mkdtemp(prefix="bench_alive_academic_")
        self._db_path = os.path.join(self._tmp_dir, "bench.db")
        memory_dir = os.path.join(self._tmp_dir, "memory")

        sdk_config = config.get("alive_config", {})

        # Benchmark defaults: let everything through for maximum recall
        # Use nested dict structure so AliveConfig.get() resolves them
        intake = sdk_config.setdefault("intake", {})
        intake.setdefault("salience_threshold", 0.0)
        intake.setdefault("max_salience_threshold", 0.0)
        intake.setdefault("max_day_moments", 999999)

        # Wire up LLM provider for consolidation
        llm = None
        self._llm_calls = 0
        self._llm_tokens = 0

        openrouter_key = config.get("api_key", os.environ.get("OPENROUTER_API_KEY", ""))
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

        try:
            from alive_memory.llm.provider import LLMResponse

            if openrouter_key:
                from alive_memory.llm.openrouter import OpenRouterProvider
                model = config.get("llm_model", "openai/gpt-4o-mini")
                _inner = OpenRouterProvider(api_key=openrouter_key, model=model)
            elif anthropic_key:
                from alive_memory.llm.anthropic import AnthropicProvider
                model = config.get("llm_model", "claude-haiku-4-5-20251001")
                _inner = AnthropicProvider(api_key=anthropic_key, model=model)
            else:
                _inner = None

            if _inner is not None:
                _adapter = self

                class _TrackingProvider:
                    async def complete(self, prompt, *, system=None, max_tokens=1000, temperature=0.7) -> LLMResponse:
                        resp = await _inner.complete(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
                        _adapter._llm_calls += 1
                        _adapter._llm_tokens += resp.input_tokens + resp.output_tokens
                        return resp

                llm = _TrackingProvider()
        except ImportError:
            pass

        # Use OpenAI embeddings if key available, otherwise local (hash-based)
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        embedder = "openai" if openai_key else "local"

        self._memory = AliveMemory(
            storage=self._db_path,
            memory_dir=memory_dir,
            config=sdk_config or None,
            llm=llm,
            embedder=embedder,
        )
        await self._memory.initialize()
        self._turn_count = 0
        self._tracker = LLMTracker()

    async def add_conversation(self, turns: list[ConversationTurn]) -> None:
        if not self._memory:
            return

        for turn in turns:
            event_type = _ROLE_TO_EVENT.get(turn.role, EventType.CONVERSATION)
            # Pass the speaker so consolidation can attribute facts correctly.
            # The content already includes "Speaker: text" so the LLM can
            # distinguish who said what — visitor_name just sets the default.
            speaker = (turn.metadata or {}).get("speaker", "")
            metadata = {
                "session_id": turn.session_id,
                "turn_id": turn.turn_id,
                "visitor_name": speaker,
            }
            if turn.timestamp:
                metadata["timestamp"] = turn.timestamp

            await self._memory.intake(
                event_type=event_type,
                content=f"[{turn.role}]: {turn.content}",
                metadata=metadata,
            )
            self._turn_count += 1

    async def consolidate(self) -> None:
        if self._memory:
            await self._memory.consolidate(depth="full")

    async def answer_query(self, query: MemoryQuery, llm_config: dict) -> str:
        if not self._memory:
            return "[error: memory not initialized]"

        # Recall from alive's three-tier memory
        ctx = await self._memory.recall(query=query.question, limit=10)

        # Build context from all tiers
        context_parts: list[str] = []

        if ctx.journal_entries:
            context_parts.append("Journal entries:\n" + "\n".join(ctx.journal_entries[:5]))
        if ctx.visitor_notes:
            context_parts.append("Visitor notes:\n" + "\n".join(ctx.visitor_notes[:3]))
        if ctx.self_knowledge:
            context_parts.append("Self-knowledge:\n" + "\n".join(ctx.self_knowledge[:3]))
        if hasattr(ctx, "reflections") and ctx.reflections:
            context_parts.append("Reflections:\n" + "\n".join(ctx.reflections[:3]))
        if ctx.totem_facts:
            context_parts.append("Known facts:\n" + "\n".join(ctx.totem_facts[:10]))
        if ctx.trait_facts:
            context_parts.append("Traits:\n" + "\n".join(ctx.trait_facts[:10]))
        if hasattr(ctx, "cold_echoes") and ctx.cold_echoes:
            context_parts.append("Historical echoes:\n" + "\n".join(ctx.cold_echoes[:3]))

        context = "\n\n".join(context_parts)

        return await llm_answer(
            question=query.question,
            context=context,
            llm_config=llm_config,
            tracker=self._tracker,
        )

    async def get_metrics(self) -> SystemMetrics:
        storage = 0
        # SQLite database (Tier 1 + Tier 3)
        if self._db_path and os.path.exists(self._db_path):
            storage = os.path.getsize(self._db_path)
            for suffix in ("-wal", "-shm"):
                wal = self._db_path + suffix
                if os.path.exists(wal):
                    storage += os.path.getsize(wal)
        # Hot memory markdown files (Tier 2: journal, visitors, threads, etc.)
        if self._tmp_dir:
            memory_dir = os.path.join(self._tmp_dir, "memory")
            if os.path.isdir(memory_dir):
                for dirpath, _dirnames, filenames in os.walk(memory_dir):
                    for f in filenames:
                        storage += os.path.getsize(os.path.join(dirpath, f))

        return SystemMetrics(
            total_llm_calls=self._tracker.total_calls + self._llm_calls,
            total_tokens=self._tracker.total_tokens + self._llm_tokens,
            storage_bytes=storage,
            memory_count=self._turn_count,
        )

    async def reset(self) -> None:
        if self._memory:
            await self._memory.close()
            self._memory = None
        # Clean up old temp directory to avoid leaking storage
        old_tmp = self._tmp_dir
        if old_tmp and os.path.isdir(old_tmp):
            import shutil
            shutil.rmtree(old_tmp, ignore_errors=True)
        self._tmp_dir = None
        self._db_path = None
        # Reinitialize with the original config so subsequent sessions work
        if hasattr(self, "_setup_config"):
            await self.setup(self._setup_config)

    async def teardown(self) -> None:
        if self._memory:
            await self._memory.close()
            self._memory = None

        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            import shutil
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
