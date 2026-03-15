"""alive-memory adapter — wraps the AliveMemory SDK for benchmarking.

Uses the public AliveMemory API (three-tier architecture):
- intake() for recording events (returns DayMoment | None)
- recall() for retrieval (returns RecallContext)
- consolidate() for sleep/maintenance (returns SleepReport)
- get_state() / get_identity() for cognitive state
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict

from alive_memory import AliveMemory, EventType
from benchmarks.adapters.base import (
    BenchEvent,
    MemoryAdapter,
    RecallResult,
    SystemStats,
)

# Map bench event types to SDK EventType enum
_EVENT_TYPE_MAP = {
    "conversation": EventType.CONVERSATION,
    "observation": EventType.OBSERVATION,
    "action": EventType.ACTION,
    "system": EventType.SYSTEM,
}


class AliveMemoryAdapter(MemoryAdapter):
    """Wraps the alive-memory SDK for benchmarking."""

    def __init__(self) -> None:
        self._memory: AliveMemory | None = None
        self._db_path: str | None = None
        self._tmp_dir: str | None = None
        self._count = 0
        self._salience_map: dict[int, float] = {}  # cycle -> salience
        self._consolidation_reports: list[dict] = []
        self._total_dreams = 0
        self._total_reflections = 0
        self._llm_calls = 0
        self._llm_tokens = 0
        self._llm_enabled = False

    async def setup(self, config: dict) -> None:
        self._tmp_dir = tempfile.mkdtemp(prefix="bench_alive_")
        self._db_path = os.path.join(self._tmp_dir, "bench.db")
        memory_dir = os.path.join(self._tmp_dir, "memory")

        sdk_config = config.get("alive_config", {})

        # Wire up LLM provider if API key available
        # Priority: OPENROUTER_API_KEY > ANTHROPIC_API_KEY
        llm = None
        self._llm_calls = 0
        self._llm_tokens = 0

        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

        try:
            from alive_memory.llm.provider import LLMResponse

            if openrouter_key:
                from alive_memory.llm.openrouter import OpenRouterProvider
                model = config.get("llm_model", "anthropic/claude-haiku-4-5")
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
            pass  # httpx or anthropic not installed

        self._memory = AliveMemory(
            storage=self._db_path,
            memory_dir=memory_dir,
            config=sdk_config or None,
            llm=llm,
        )
        await self._memory.initialize()
        self._count = 0
        self._llm_enabled = llm is not None

    async def ingest(self, event: BenchEvent) -> None:
        if not self._memory:
            return

        self._count += 1
        event_type = _EVENT_TYPE_MAP.get(event.event_type, EventType.CONVERSATION)

        moment = await self._memory.intake(
            event_type=event_type,
            content=event.content,
            metadata=event.metadata,
        )

        # Capture salience if DayMoment returned
        if moment is not None and hasattr(moment, "salience"):
            self._salience_map[event.cycle] = float(moment.salience)

    async def recall(self, query: str, limit: int = 5) -> list[RecallResult]:
        if not self._memory:
            return []

        ctx = await self._memory.recall(query=query, limit=limit)

        results = []
        # Convert RecallContext entries to RecallResults
        # Journal entries are "hot" tier (recent working memory)
        for entry in ctx.journal_entries:
            results.append(
                RecallResult(
                    content=entry,
                    score=1.0,
                    metadata={"source": "journal", "tier": "hot"},
                )
            )
        for note in ctx.visitor_notes:
            results.append(
                RecallResult(
                    content=note,
                    score=0.9,
                    metadata={"source": "visitors", "tier": "hot"},
                )
            )
        for knowledge in ctx.self_knowledge:
            results.append(
                RecallResult(
                    content=knowledge,
                    score=0.8,
                    metadata={"source": "self", "tier": "cold"},
                )
            )

        # Include reflections if available (cold tier — consolidated insights)
        if hasattr(ctx, "reflections"):
            for ref in ctx.reflections or []:
                content = ref if isinstance(ref, str) else str(ref)
                results.append(
                    RecallResult(
                        content=content,
                        score=0.7,
                        metadata={"source": "reflection", "tier": "cold"},
                    )
                )

        # Include cold echoes if available
        if hasattr(ctx, "cold_echoes"):
            for echo in ctx.cold_echoes or []:
                content = echo if isinstance(echo, str) else str(echo)
                results.append(
                    RecallResult(
                        content=content,
                        score=0.6,
                        metadata={"source": "cold_echo", "tier": "cold"},
                    )
                )

        return results[:limit]

    async def consolidate(self) -> None:
        if not self._memory:
            return
        report = await self._memory.consolidate(depth="nap")

        # Capture consolidation report if SleepReport returned
        if report is not None:
            report_data = {}
            if hasattr(report, "dreams"):
                dreams = report.dreams or []
                report_data["dreams"] = [str(d) for d in dreams]
                self._total_dreams += len(dreams)
            if hasattr(report, "reflections"):
                reflections = report.reflections or []
                report_data["reflections"] = [str(r) for r in reflections]
                self._total_reflections += len(reflections)
            if report_data:
                self._consolidation_reports.append(report_data)

    async def get_state(self) -> dict | None:
        if not self._memory:
            return None

        try:
            state = await self._memory.get_state()
            identity = await self._memory.get_identity()
            return {
                "mood": asdict(state.mood),
                "drives": asdict(state.drives),
                "energy": state.energy,
                "cycle_count": state.cycle_count,
                "memories_total": state.memories_total,
                "identity": {
                    "traits": identity.traits,
                    "behavioral_summary": identity.behavioral_summary,
                    "version": identity.version,
                },
            }
        except Exception:
            return None

    async def get_adapter_data(self) -> dict:
        return {
            "salience_map": dict(self._salience_map),
            "consolidation_reports": list(self._consolidation_reports),
            "total_dreams": self._total_dreams,
            "total_reflections": self._total_reflections,
        }

    async def get_stats(self) -> SystemStats:
        storage = 0
        if self._db_path and os.path.exists(self._db_path):
            storage = os.path.getsize(self._db_path)
            for suffix in ("-wal", "-shm"):
                wal = self._db_path + suffix
                if os.path.exists(wal):
                    storage += os.path.getsize(wal)

        return SystemStats(
            memory_count=self._count,
            storage_bytes=storage,
            total_llm_calls=self._llm_calls,
            total_tokens=self._llm_tokens,
        )

    async def teardown(self) -> None:
        if self._memory:
            await self._memory.close()
            self._memory = None

        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            import shutil
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
