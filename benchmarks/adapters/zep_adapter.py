"""Zep adapter — conversation memory with summaries + fact extraction.

Uses Zep's recommended configuration with the cloud or local server.
"""

import sys
import uuid
from typing import Optional

from benchmarks.adapters.base import (
    BenchEvent,
    MemoryAdapter,
    RecallResult,
    SystemStats,
)

try:
    from zep_cloud.client import Zep as ZepClient
    from zep_cloud.types import Message

    ZEP_AVAILABLE = True
except ImportError:
    try:
        from zep_python import ZepClient  # type: ignore[assignment]
        from zep_python.types import Message  # type: ignore[assignment]

        ZEP_AVAILABLE = True
    except ImportError:
        ZEP_AVAILABLE = False
        ZepClient = None  # type: ignore[assignment, misc]
        Message = None  # type: ignore[assignment, misc]


class ZepAdapter(MemoryAdapter):
    """Zep client wrapper using recommended configuration."""

    def __init__(self) -> None:
        self._client = None
        self._session_id = ""
        self._count = 0
        self._llm_calls = 0
        self._llm_tokens = 0

    async def setup(self, config: dict) -> None:
        if not ZEP_AVAILABLE:
            raise ImportError(
                "zep-cloud or zep-python required: pip install zep-cloud"
            )

        api_key = config.get("zep_api_key", "")
        base_url = config.get("zep_base_url", "")

        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url

        self._client = ZepClient(**kwargs)
        self._session_id = f"bench_{uuid.uuid4().hex[:8]}"
        self._count = 0
        self._llm_calls = 0
        self._llm_tokens = 0

        # Create session
        try:
            self._client.memory.add_session(session_id=self._session_id)
        except Exception:
            pass  # session may already exist

    async def ingest(self, event: BenchEvent) -> None:
        role = "human" if event.event_type == "conversation" else "ai"

        msg = Message(
            role=role,
            role_type=role,
            content=event.content,
            metadata={
                "cycle": event.cycle,
                "type": event.event_type,
                "timestamp": event.timestamp,
            },
        )

        try:
            self._client.memory.add(
                session_id=self._session_id, messages=[msg]
            )
        except Exception:
            pass

        self._count += 1
        # Zep does background processing (summarization, entity extraction)
        self._llm_calls += 1
        self._llm_tokens += len(event.content) // 4 + 50

    async def recall(self, query: str, limit: int = 5) -> list[RecallResult]:
        if not self._client:
            return []

        try:
            search_results = self._client.memory.search(
                session_id=self._session_id,
                text=query,
                limit=limit,
                search_type="similarity",
            )
        except Exception:
            return []

        recalls = []
        for result in search_results:
            content = getattr(result, "message", {})
            if isinstance(content, dict):
                text = content.get("content", "")
            else:
                text = getattr(content, "content", str(content))

            score = getattr(result, "score", 1.0) or 1.0
            meta = getattr(result, "metadata", {}) or {}

            recalls.append(RecallResult(
                content=text,
                score=float(score),
                metadata=meta if isinstance(meta, dict) else {},
                formed_at=None,
            ))

        return recalls[:limit]

    async def get_stats(self) -> SystemStats:
        mem_count = self._count
        storage = 0

        if self._client:
            try:
                memory = self._client.memory.get(session_id=self._session_id)
                messages = getattr(memory, "messages", []) or []
                mem_count = len(messages)
                storage = sum(
                    sys.getsizeof(getattr(m, "content", "")) for m in messages
                )
            except Exception:
                pass

        return SystemStats(
            memory_count=mem_count,
            storage_bytes=storage,
            total_llm_calls=self._llm_calls,
            total_tokens=self._llm_tokens,
        )

    async def teardown(self) -> None:
        if self._client and self._session_id:
            try:
                self._client.memory.delete(session_id=self._session_id)
            except Exception:
                pass
        self._client = None
