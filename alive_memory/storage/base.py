"""BaseStorage ABC — interface all storage backends must implement.

Every method that touches the database is async.  Implementations
may use SQLite, Postgres, in-memory dicts, or anything else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from alive_memory.types import (
    CognitiveState,
    ConsolidationReport,
    DriveState,
    Memory,
    MoodState,
    SelfModel,
)


class BaseStorage(ABC):
    """Abstract base class for alive-memory storage backends."""

    # ── Memory CRUD ──────────────────────────────────────────────

    @abstractmethod
    async def store_memory(self, memory: Memory) -> str:
        """Store a new memory. Returns the memory ID."""
        ...

    @abstractmethod
    async def get_memory(self, memory_id: str) -> Optional[Memory]:
        """Retrieve a single memory by ID. Returns None if not found."""
        ...

    @abstractmethod
    async def search_memories(
        self,
        embedding: list[float],
        limit: int = 5,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[Memory]:
        """Search memories by embedding similarity.

        Args:
            embedding: Query embedding vector.
            limit: Maximum results.
            filters: Optional key-value filters (e.g. memory_type, min_strength).

        Returns:
            List of memories ordered by relevance.
        """
        ...

    @abstractmethod
    async def search_memories_by_text(
        self,
        query: str,
        limit: int = 5,
    ) -> list[Memory]:
        """Full-text search over memory content. Fallback when no embedding."""
        ...

    @abstractmethod
    async def update_memory_strength(
        self, memory_id: str, strength: float
    ) -> None:
        """Update a memory's consolidation strength."""
        ...

    @abstractmethod
    async def update_memory_recall(self, memory_id: str) -> None:
        """Record a recall event: increment recall_count, set last_recalled."""
        ...

    @abstractmethod
    async def delete_memory(self, memory_id: str) -> None:
        """Permanently remove a memory."""
        ...

    @abstractmethod
    async def get_memories_for_consolidation(
        self, min_age_hours: float = 1.0
    ) -> list[Memory]:
        """Get memories eligible for consolidation (sleep).

        Returns memories older than min_age_hours, ordered by strength ASC.
        """
        ...

    @abstractmethod
    async def merge_memories(
        self, source_ids: list[str], merged: Memory
    ) -> None:
        """Delete source memories and insert the merged result."""
        ...

    @abstractmethod
    async def count_memories(self) -> int:
        """Return total number of stored memories."""
        ...

    # ── Drive State ──────────────────────────────────────────────

    @abstractmethod
    async def get_drive_state(self) -> DriveState:
        """Get the current drive levels."""
        ...

    @abstractmethod
    async def set_drive_state(self, state: DriveState) -> None:
        """Persist updated drive levels."""
        ...

    # ── Mood State ───────────────────────────────────────────────

    @abstractmethod
    async def get_mood_state(self) -> MoodState:
        """Get the current mood."""
        ...

    @abstractmethod
    async def set_mood_state(self, state: MoodState) -> None:
        """Persist updated mood."""
        ...

    # ── Cognitive State ──────────────────────────────────────────

    @abstractmethod
    async def get_cognitive_state(self) -> CognitiveState:
        """Get the full cognitive state snapshot."""
        ...

    @abstractmethod
    async def set_cognitive_state(self, state: CognitiveState) -> None:
        """Persist the full cognitive state."""
        ...

    # ── Self-Model (Identity) ────────────────────────────────────

    @abstractmethod
    async def get_self_model(self) -> SelfModel:
        """Get the current self-model."""
        ...

    @abstractmethod
    async def save_self_model(self, model: SelfModel) -> None:
        """Persist an updated self-model."""
        ...

    # ── Parameters ───────────────────────────────────────────────

    @abstractmethod
    async def get_parameters(self) -> dict[str, float]:
        """Get all cognitive parameters as key→value dict."""
        ...

    @abstractmethod
    async def set_parameter(
        self, key: str, value: float, reason: str = ""
    ) -> None:
        """Set a single parameter, logging the change."""
        ...

    # ── Cycle Log ────────────────────────────────────────────────

    @abstractmethod
    async def log_cycle(self, entry: dict[str, Any]) -> None:
        """Append a cycle audit log entry."""
        ...

    @abstractmethod
    async def get_cycle_count(self) -> int:
        """Return the total number of logged cycles."""
        ...

    # ── Consolidation Log ────────────────────────────────────────

    @abstractmethod
    async def log_consolidation(self, report: ConsolidationReport) -> None:
        """Persist a consolidation (sleep) report."""
        ...

    # ── Lifecycle ────────────────────────────────────────────────

    @abstractmethod
    async def initialize(self) -> None:
        """Set up storage: create tables, run migrations.

        Safe to call on every startup (idempotent).
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources (connections, file handles)."""
        ...
