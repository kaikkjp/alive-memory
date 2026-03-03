"""Base adapter interface for benchmarked memory systems.

Every memory system implements MemoryAdapter. The interface is intentionally
minimal — 4 required methods, 3 optional — so adding a new system is easy.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BenchEvent:
    """A single event in the benchmark stream."""

    cycle: int
    event_type: str  # conversation | observation | action | system
    content: str
    metadata: dict
    timestamp: str  # ISO 8601

    @classmethod
    def from_dict(cls, d: dict) -> "BenchEvent":
        return cls(
            cycle=d["cycle"],
            event_type=d["event_type"],
            content=d["content"],
            metadata=d.get("metadata", {}),
            timestamp=d["timestamp"],
        )


@dataclass
class RecallResult:
    """A single recalled memory.

    Systems that don't provide relevance scores should set score=1.0.
    The benchmark scoring uses ground truth matching, not adapter scores.
    """

    content: str
    score: float  # system's own relevance score (normalized 0-1)
    metadata: dict = field(default_factory=dict)
    formed_at: Optional[str] = None  # when this memory was formed


@dataclass
class SystemStats:
    """Resource usage snapshot.

    For in-memory systems, use process RSS delta for storage_bytes,
    not disk I/O (which would report 0).
    """

    memory_count: int  # total stored memories/entries
    storage_bytes: int  # disk/memory usage
    total_llm_calls: int  # LLM calls for memory ops (not agent reasoning)
    total_tokens: int  # tokens consumed by memory operations


class MemoryAdapter(ABC):
    """Interface every benchmarked system must implement."""

    @abstractmethod
    async def setup(self, config: dict) -> None:
        """Initialize the memory system. Called once before benchmark starts."""
        ...

    @abstractmethod
    async def ingest(self, event: BenchEvent) -> None:
        """Record an event. Called once per cycle with that cycle's event."""
        ...

    @abstractmethod
    async def recall(self, query: str, limit: int = 5) -> list[RecallResult]:
        """Retrieve relevant memories for a query."""
        ...

    @abstractmethod
    async def get_stats(self) -> SystemStats:
        """Return current resource usage."""
        ...

    async def consolidate(self) -> None:
        """Run any maintenance/consolidation the system supports.

        Called periodically (configurable). No-op by default.
        """
        pass

    async def get_state(self) -> Optional[dict]:
        """Return internal cognitive state if tracked.

        Drives, mood, energy, etc. None if not supported.
        """
        return None

    async def get_adapter_data(self) -> dict:
        """Return adapter-specific data for specialized metrics.

        Override to expose internal data (salience maps, consolidation
        reports, etc.) that adapter-specific metrics can consume.
        """
        return {}

    async def forget(self, content_hint: str) -> bool:
        """Ask the memory system to forget content matching the hint.

        Returns True if the system supports and performed forgetting.
        """
        return False

    async def teardown(self) -> None:
        """Cleanup. Called once after benchmark completes."""
        pass
