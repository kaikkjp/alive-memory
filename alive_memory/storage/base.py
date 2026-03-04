"""BaseStorage ABC — interface all storage backends must implement.

Three-tier architecture:
  Tier 1 — day_memory: ephemeral salient moments (SQLite)
  Tier 3 — cold_embeddings: vector archive (SQLite, sleep-only)
  (Tier 2 is hot memory on disk, not in storage backend)

Every method that touches the database is async.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from alive_memory.types import (
    CognitiveState,
    DayMoment,
    DriveState,
    MoodState,
    SelfModel,
    SleepReport,
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
    async def get_lowest_salience_moment(self) -> Optional[DayMoment]:
        """Get the moment with the lowest salience (for eviction)."""
        ...

    @abstractmethod
    async def delete_moment(self, moment_id: str) -> None:
        """Delete a single moment (for eviction)."""
        ...

    @abstractmethod
    async def get_recent_moment_content(
        self, window_minutes: int = 30
    ) -> list[str]:
        """Get content of recent moments for dedup checking."""
        ...

    # ── Cold Embeddings (Tier 3) ──────────────────────────────────

    @abstractmethod
    async def store_cold_embedding(
        self,
        content: str,
        embedding: list[float],
        source_moment_id: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Store an embedding in the cold archive. Returns embedding ID."""
        ...

    @abstractmethod
    async def search_cold(
        self,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search cold embeddings by cosine similarity.

        Returns list of dicts with keys: id, content, score, metadata.
        Used during sleep only for finding "cold echoes".
        """
        ...

    @abstractmethod
    async def count_cold_embeddings(self) -> int:
        """Return total number of cold embeddings."""
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

    # ── Lifecycle ────────────────────────────────────────────────

    @abstractmethod
    async def initialize(self) -> None:
        """Set up storage: create tables, run migrations. Idempotent."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
