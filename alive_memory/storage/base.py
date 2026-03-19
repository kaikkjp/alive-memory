"""BaseStorage ABC — interface all storage backends must implement.

Three-tier architecture:
  Tier 1 — day_memory: ephemeral salient moments (SQLite)
  Tier 3 — cold_embeddings: vector archive (SQLite, sleep-only)
  (Tier 2 is hot memory on disk, not in storage backend)

Every method that touches the database is async.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from alive_memory.types import (
    CognitiveState,
    DayMoment,
    DriveState,
    MoodState,
    SelfModel,
    SleepReport,
    Totem,
    Visitor,
    VisitorTrait,
)


class BaseStorage(ABC):
    """Abstract base class for alive-memory storage backends."""

    # ── Day Memory (Tier 1) ───────────────────────────────────────

    @abstractmethod
    async def record_moment(self, moment: DayMoment) -> str:
        """Record a salient moment. Returns the moment ID."""
        ...

    @abstractmethod
    async def get_unprocessed_moments(self, nap: bool = False) -> list[DayMoment]:
        """Get moments not yet processed by consolidation.

        Args:
            nap: If True, return moments not yet nap-processed.
                 If False, return moments not yet fully processed.
        """
        ...

    @abstractmethod
    async def mark_moment_processed(
        self, moment_id: str, nap: bool = False
    ) -> None:
        """Mark a moment as processed.

        Args:
            nap: If True, mark nap_processed. If False, mark processed.
        """
        ...

    @abstractmethod
    async def flush_day_memory(self) -> int:
        """Delete all processed moments. Returns count deleted."""
        ...

    @abstractmethod
    async def flush_stale_moments(self, stale_hours: int = 72) -> int:
        """Delete unprocessed moments older than stale_hours. Returns count deleted."""
        ...

    @abstractmethod
    async def get_day_memory_count(self) -> int:
        """Return the number of unprocessed moments in day memory."""
        ...

    @abstractmethod
    async def get_lowest_salience_moment(self) -> DayMoment | None:
        """Get the moment with the lowest salience (for eviction)."""
        ...

    @abstractmethod
    async def delete_moment(self, moment_id: str) -> None:
        """Delete a single moment (for eviction)."""
        ...

    @abstractmethod
    async def get_recent_moment_content(
        self, window_minutes: int = 30, *, reference_time: str | None = None
    ) -> list[str]:
        """Get content of recent moments for dedup checking.

        Args:
            window_minutes: How many minutes back to look.
            reference_time: ISO 8601 reference time (defaults to wall clock).
        """
        ...

    # ── Drive State ──────────────────────────────────────────────

    @abstractmethod
    async def get_drive_state(self) -> DriveState:
        ...

    @abstractmethod
    async def set_drive_state(self, state: DriveState) -> None:
        ...

    # ── Mood State ───────────────────────────────────────────────

    @abstractmethod
    async def get_mood_state(self) -> MoodState:
        ...

    @abstractmethod
    async def set_mood_state(self, state: MoodState) -> None:
        ...

    # ── Cognitive State ──────────────────────────────────────────

    @abstractmethod
    async def get_cognitive_state(self) -> CognitiveState:
        ...

    @abstractmethod
    async def set_cognitive_state(self, state: CognitiveState) -> None:
        ...

    # ── Self-Model (Identity) ────────────────────────────────────

    @abstractmethod
    async def get_self_model(self) -> SelfModel:
        ...

    @abstractmethod
    async def save_self_model(self, model: SelfModel) -> None:
        ...

    # ── Drift Baseline ──────────────────────────────────────────

    @abstractmethod
    async def get_drift_baseline(self) -> dict[str, Any]:
        """Get the current behavioral baseline for drift detection."""
        ...

    @abstractmethod
    async def save_drift_baseline(self, baseline: dict[str, Any]) -> None:
        """Save updated behavioral baseline."""
        ...

    # ── Evolution Decision Log ───────────────────────────────────

    @abstractmethod
    async def log_evolution_decision(self, decision: dict[str, Any]) -> None:
        """Log an identity evolution decision for audit trail."""
        ...

    # ── Parameters ───────────────────────────────────────────────

    @abstractmethod
    async def get_parameters(self) -> dict[str, float]:
        ...

    @abstractmethod
    async def set_parameter(
        self, key: str, value: float, reason: str = ""
    ) -> None:
        ...

    # ── Meta Experiments ─────────────────────────────────────────

    @abstractmethod
    async def save_experiment(self, experiment: dict[str, Any]) -> None:
        """Persist a meta-controller experiment."""
        ...

    @abstractmethod
    async def get_pending_experiments(self, min_age_cycles: int = 0) -> list[dict[str, Any]]:
        """Get experiments with outcome='pending', optionally age-gated by cycle count."""
        ...

    @abstractmethod
    async def update_experiment(self, experiment_id: str, updates: dict[str, Any]) -> None:
        """Update an experiment's outcome, confidence, side_effects, evaluated_at."""
        ...

    @abstractmethod
    async def get_confidence(self, param_key: str, metric_name: str) -> float:
        """Get persisted confidence for a param→metric link. Returns 0.5 if none."""
        ...

    @abstractmethod
    async def set_confidence(self, param_key: str, metric_name: str, confidence: float) -> None:
        """Persist confidence for a param→metric link."""
        ...

    @abstractmethod
    async def get_parameter_bounds(self, key: str) -> tuple[float | None, float | None]:
        """Get (min_bound, max_bound) for a parameter. Returns (None, None) if unset."""
        ...

    # ── Cycle Log ────────────────────────────────────────────────

    @abstractmethod
    async def log_cycle(self, entry: dict[str, Any]) -> None:
        ...

    @abstractmethod
    async def get_cycle_count(self) -> int:
        ...

    # ── Consolidation Log ────────────────────────────────────────

    @abstractmethod
    async def log_consolidation(self, report: SleepReport) -> None:
        ...

    # ── Totems (Semantic Facts) ────────────────────────────────────

    @abstractmethod
    async def insert_totem(
        self,
        entity: str,
        *,
        visitor_id: str | None = None,
        weight: float = 0.5,
        context: str = "",
        category: str = "general",
        source_moment_id: str | None = None,
        source_session_id: str | None = None,
        source_turn_id: str | None = None,
    ) -> str:
        """Insert a totem (semantic fact). Returns totem ID."""
        ...

    @abstractmethod
    async def get_totems(
        self,
        *,
        visitor_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 10,
    ) -> list[Totem]:
        """Get totems, optionally filtered by visitor."""
        ...

    @abstractmethod
    async def search_totems(self, query: str, *, limit: int = 10) -> list[Totem]:
        """Search totems by entity or context keyword match."""
        ...

    @abstractmethod
    async def update_totem_weight(
        self, entity: str, *, visitor_id: str | None = None, weight: float
    ) -> None:
        """Update a totem's weight and last_referenced timestamp."""
        ...

    # ── Visitor Traits ──────────────────────────────────────────────

    @abstractmethod
    async def insert_trait(
        self,
        visitor_id: str,
        trait_category: str,
        trait_key: str,
        trait_value: str,
        *,
        confidence: float = 0.5,
        source_moment_id: str | None = None,
        source_session_id: str | None = None,
        source_turn_id: str | None = None,
    ) -> str:
        """Insert a trait observation. Returns trait ID."""
        ...

    @abstractmethod
    async def get_traits(
        self, visitor_id: str, *, category: str | None = None, limit: int = 20
    ) -> list[VisitorTrait]:
        """Get traits for a visitor, optionally filtered by category."""
        ...

    @abstractmethod
    async def search_traits(self, query: str, *, limit: int = 10) -> list[VisitorTrait]:
        """Search traits by key or value keyword match."""
        ...

    @abstractmethod
    async def get_latest_trait(
        self, visitor_id: str, category: str, key: str
    ) -> VisitorTrait | None:
        """Get the most recent trait observation for a specific key."""
        ...

    # ── Unified Cold Memory ─────────────────────────────────────────

    @abstractmethod
    async def store_cold_memory(
        self,
        content: str,
        embedding: list[float] | None,
        entry_type: str,
        *,
        raw_content: str | None = None,
        visitor_id: str | None = None,
        weight: float = 1.0,
        category: str = "",
        metadata: dict[str, Any] | None = None,
        source_moment_id: str | None = None,
        session_id: str | None = None,
        turn_index: int | None = None,
        role: str | None = None,
        created_at: str | None = None,
    ) -> str:
        """Store an entry in the unified cold memory archive. Returns entry ID."""
        ...

    @abstractmethod
    async def search_cold_memory(
        self,
        embedding: list[float],
        *,
        limit: int = 10,
        entry_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over unified cold memory.

        Returns list of dicts with keys: id, content, raw_content, entry_type,
        visitor_id, weight, category, metadata, score.
        """
        ...

    # ── Raw Turn Retrieval ────────────────────────────────────────────

    @abstractmethod
    async def get_turns_by_session(
        self,
        session_id: str,
        *,
        start_turn: int | None = None,
        end_turn: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw turns from a session, optionally within a turn range.

        Returns list of dicts with keys: id, content, raw_content, entry_type,
        session_id, turn_index, role, created_at.
        Ordered by turn_index ASC.
        """
        ...

    @abstractmethod
    async def get_neighboring_turns(
        self,
        session_id: str,
        turn_index: int,
        *,
        window: int = 3,
    ) -> list[dict[str, Any]]:
        """Fetch turns around a specific turn_index in a session.

        Returns up to 2*window+1 turns centered on turn_index.
        Ordered by turn_index ASC.
        """
        ...

    # ── Visitors ────────────────────────────────────────────────────

    @abstractmethod
    async def upsert_visitor(
        self,
        visitor_id: str,
        name: str,
        *,
        emotional_imprint: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Create or update a visitor record. Increments visit_count on update."""
        ...

    @abstractmethod
    async def get_visitor(self, visitor_id: str) -> Visitor | None:
        """Get a visitor by ID."""
        ...

    @abstractmethod
    async def search_visitors(self, query: str, *, limit: int = 5) -> list[Visitor]:
        """Search visitors by name or summary."""
        ...

    # ── Lifecycle ────────────────────────────────────────────────

    @abstractmethod
    async def initialize(self) -> None:
        """Set up storage: create tables, run migrations. Idempotent."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
