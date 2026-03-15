"""Mem0 adapter — graph-based memory with entity/fact extraction.

Uses Mem0's recommended configuration. Expected to excel at entity_tracking
and multi_hop queries due to its graph-based architecture.
"""

import contextlib
import os
import sys
import tempfile

from benchmarks.adapters.base import (
    BenchEvent,
    MemoryAdapter,
    RecallResult,
    SystemStats,
)

try:
    from mem0 import Memory
except ImportError:
    Memory = None  # type: ignore[assignment, misc]


class Mem0Adapter(MemoryAdapter):
    """Mem0 client wrapper using recommended configuration."""

    def __init__(self) -> None:
        self._memory = None
        self._user_id = "bench_user"
        self._count = 0
        self._llm_calls = 0
        self._llm_tokens = 0
        self._tmp_dir: str | None = None

    async def setup(self, config: dict) -> None:
        if Memory is None:
            raise ImportError("mem0ai required: pip install mem0ai")

        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")

        # Build LLM config: prefer OpenRouter, fall back to Anthropic, then OpenAI
        if openrouter_key:
            llm_config = {
                "provider": "openai",
                "config": {
                    "model": config.get("llm_model", "anthropic/claude-haiku-4-5"),
                    "temperature": 0,
                    "openai_base_url": "https://openrouter.ai/api/v1",
                    "api_key": openrouter_key,
                },
            }
        elif anthropic_key:
            llm_config = {
                "provider": "anthropic",
                "config": {
                    "model": config.get("llm_model", "claude-haiku-4-5-20251001"),
                    "temperature": 0,
                    "api_key": anthropic_key,
                },
            }
        elif openai_key:
            llm_config = {
                "provider": "openai",
                "config": {
                    "model": config.get("llm_model", "gpt-4o-mini"),
                    "temperature": 0,
                    "api_key": openai_key,
                },
            }
        else:
            raise RuntimeError(
                "No LLM API key found. Set OPENROUTER_API_KEY, ANTHROPIC_API_KEY, "
                "or OPENAI_API_KEY."
            )

        # Local SQLite vector store to avoid needing a running Qdrant
        self._tmp_dir = tempfile.mkdtemp(prefix="bench_mem0_")
        db_path = os.path.join(self._tmp_dir, "mem0.db")

        mem0_config = config.get("mem0_config", {
            "llm": llm_config,
            "embedder": {
                "provider": "huggingface",
                "config": {
                    "model": "all-MiniLM-L6-v2",
                },
            },
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": "bench_mem0",
                    "path": db_path,
                },
            },
            "version": "v1.1",
        })

        self._memory = Memory.from_config(mem0_config)
        self._user_id = config.get("user_id", "bench_user")
        self._count = 0
        self._llm_calls = 0
        self._llm_tokens = 0

    async def ingest(self, event: BenchEvent) -> None:
        # Mem0 extracts entities and facts from content
        metadata = {
            "cycle": event.cycle,
            "type": event.event_type,
            "timestamp": event.timestamp,
        }
        metadata.update(event.metadata)

        self._memory.add(
            event.content,
            user_id=self._user_id,
            metadata=metadata,
        )
        self._count += 1
        # Mem0 makes LLM calls for entity extraction
        self._llm_calls += 1
        self._llm_tokens += len(event.content) // 4 + 100

    async def recall(self, query: str, limit: int = 5) -> list[RecallResult]:
        if not self._memory:
            return []

        results = self._memory.search(
            query, user_id=self._user_id, limit=limit
        )
        self._llm_calls += 1

        recalls = []
        # Mem0 returns list of dicts with 'memory', 'score', etc.
        items = results if isinstance(results, list) else results.get("results", [])
        for item in items[:limit]:
            content = item.get("memory", "") if isinstance(item, dict) else str(item)
            score = item.get("score", 1.0) if isinstance(item, dict) else 1.0
            meta = item.get("metadata", {}) if isinstance(item, dict) else {}

            recalls.append(RecallResult(
                content=content,
                score=float(score),
                metadata=meta,
                formed_at=meta.get("timestamp") if isinstance(meta, dict) else None,
            ))

        return recalls

    async def get_stats(self) -> SystemStats:
        # Get all memories to count
        all_memories = []
        if self._memory:
            try:
                all_memories = self._memory.get_all(user_id=self._user_id)
                if isinstance(all_memories, dict):
                    all_memories = all_memories.get("results", [])
            except Exception:
                pass

        storage = sum(
            sys.getsizeof(str(m)) for m in all_memories
        )

        return SystemStats(
            memory_count=len(all_memories),
            storage_bytes=storage,
            total_llm_calls=self._llm_calls,
            total_tokens=self._llm_tokens,
        )

    async def teardown(self) -> None:
        if self._memory:
            with contextlib.suppress(Exception):
                self._memory.delete_all(user_id=self._user_id)
        self._memory = None

        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            import shutil
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
