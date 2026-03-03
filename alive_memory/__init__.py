"""alive-memory: Cognitive memory layer for persistent AI characters.

Usage:
    from alive_memory import AliveMemory

    memory = AliveMemory(storage="sqlite:///memory.db")
    await memory.initialize()

    # Record something
    await memory.intake(event_type="conversation", content="Hello world")

    # Remember it
    results = await memory.recall(query="greetings", limit=3)

    # Consolidate (sleep)
    report = await memory.consolidate()

    # Check state
    state = await memory.state
    identity = await memory.identity
"""

from __future__ import annotations

__version__ = "0.1.0"

from datetime import datetime, timezone
from typing import Any

from alive_memory.config import AliveConfig
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.embeddings.local import LocalEmbeddingProvider
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import (
    CognitiveState,
    ConsolidationReport,
    DriveState,
    EventType,
    Memory,
    MemoryType,
    MoodState,
    Perception,
    SelfModel,
)

__all__ = [
    "AliveMemory",
    "AliveConfig",
    "BaseStorage",
    "SQLiteStorage",
    "LLMProvider",
    "EmbeddingProvider",
    "CognitiveState",
    "ConsolidationReport",
    "DriveState",
    "EventType",
    "Memory",
    "MemoryType",
    "MoodState",
    "Perception",
    "SelfModel",
]


class AliveMemory:
    """Public API for the alive-memory cognitive memory layer.

    Wires together storage, embeddings, LLM, and all cognitive
    subsystems (intake, recall, consolidation, identity, meta).
    """

    def __init__(
        self,
        storage: BaseStorage | str = "memory.db",
        *,
        config: AliveConfig | dict | str | None = None,
        llm: LLMProvider | None = None,
        embedder: EmbeddingProvider | None = None,
    ):
        """Initialize AliveMemory.

        Args:
            storage: A BaseStorage instance, or a string path for SQLite.
                     "sqlite:///path" or just "path.db" both work.
            config: AliveConfig instance, dict, or YAML file path.
            llm: LLM provider (needed for consolidation dreaming/reflection).
            embedder: Embedding provider (needed for vector search).
                      Defaults to LocalEmbeddingProvider if not provided.
        """
        # Storage
        if isinstance(storage, str):
            path = storage
            if path.startswith("sqlite:///"):
                path = path[len("sqlite:///"):]
            self._storage = SQLiteStorage(path)
        else:
            self._storage = storage

        # Config
        if isinstance(config, AliveConfig):
            self._config = config
        elif isinstance(config, (str, dict)):
            self._config = AliveConfig(config)
        else:
            self._config = AliveConfig()

        # LLM
        self._llm = llm

        # Embedder (default to local hash-based)
        self._embedder = embedder or LocalEmbeddingProvider(
            dimensions=self._config.get("memory.embedding_dimensions", 384)
        )

    async def initialize(self) -> None:
        """Set up storage (create tables, run migrations). Call once before use."""
        await self._storage.initialize()

    async def close(self) -> None:
        """Release resources."""
        await self._storage.close()

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    # ── Intake ───────────────────────────────────────────────────

    async def intake(
        self,
        event_type: str | EventType,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> Memory:
        """Record an event and form a memory.

        Pipeline: event → perception → affect → drives → memory formation

        Args:
            event_type: Type of event (conversation, action, observation, system).
            content: The event content/text.
            metadata: Additional metadata.
            timestamp: Event time (defaults to now UTC).

        Returns:
            The formed Memory.
        """
        from alive_memory.intake.thalamus import perceive
        from alive_memory.intake.affect import apply_affect
        from alive_memory.intake.drives import update_drives, update_mood
        from alive_memory.intake.formation import form_memory

        # Step 1: Perceive
        perception = perceive(
            event_type, content,
            config=self._config,
            metadata=metadata,
            timestamp=timestamp,
        )

        # Step 2: Affect lens
        mood = await self._storage.get_mood_state()
        drives = await self._storage.get_drive_state()
        perception = apply_affect(perception, mood, drives)

        # Step 3: Update drives
        new_drives = update_drives(
            drives, [perception], elapsed_hours=0.0,
            config=self._config,
        )
        await self._storage.set_drive_state(new_drives)

        # Step 4: Update mood
        new_mood = update_mood(
            mood, new_drives, [perception], elapsed_hours=0.0,
            config=self._config,
        )
        await self._storage.set_mood_state(new_mood)

        # Step 5: Form memory
        memory = await form_memory(
            perception, new_mood, new_drives, self._storage,
            embedder=self._embedder,
            config=self._config,
        )

        return memory

    # ── Recall ───────────────────────────────────────────────────

    async def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        min_strength: float = 0.0,
    ) -> list[Memory]:
        """Retrieve memories relevant to a query.

        Uses vector search + cognitive re-ranking.

        Args:
            query: Search query text.
            limit: Maximum results.
            min_strength: Filter out memories below this strength.

        Returns:
            List of memories ordered by relevance.
        """
        from alive_memory.recall.hippocampus import recall as _recall

        state = await self._storage.get_cognitive_state()
        return await _recall(
            query, self._storage, state,
            embedder=self._embedder,
            limit=limit,
            min_strength=min_strength,
            config=self._config,
        )

    # ── Consolidation ────────────────────────────────────────────

    async def consolidate(
        self,
        *,
        whispers: list[dict] | None = None,
        depth: str = "full",
    ) -> ConsolidationReport:
        """Run memory consolidation (sleep).

        Phases: strengthen → decay → merge → prune → dream → reflect

        Args:
            whispers: Config changes to process as dream perceptions.
            depth: "full" for complete consolidation, "nap" for light.

        Returns:
            ConsolidationReport with statistics.
        """
        from alive_memory.consolidation import consolidate as _consolidate

        return await _consolidate(
            self._storage,
            llm=self._llm,
            config=self._config,
            whispers=whispers,
            depth=depth,
        )

    # ── State ────────────────────────────────────────────────────

    @property
    def storage(self) -> BaseStorage:
        """Access the underlying storage backend."""
        return self._storage

    async def get_state(self) -> CognitiveState:
        """Get the current cognitive state."""
        return await self._storage.get_cognitive_state()

    async def get_identity(self) -> SelfModel:
        """Get the current self-model."""
        return await self._storage.get_self_model()

    # ── Drive Management ─────────────────────────────────────────

    async def update_drive(self, drive: str, delta: float) -> DriveState:
        """Manually adjust a drive value.

        Args:
            drive: Drive name (curiosity, social, expression, rest).
            delta: Change amount (positive or negative).

        Returns:
            Updated DriveState.
        """
        drives = await self._storage.get_drive_state()
        current = getattr(drives, drive, 0.5)
        setattr(drives, drive, max(0.0, min(1.0, current + delta)))
        await self._storage.set_drive_state(drives)
        return drives

    # ── Backstory Injection ──────────────────────────────────────

    async def inject_backstory(
        self,
        content: str,
        *,
        title: str | None = None,
    ) -> Memory:
        """Inject a backstory memory (pre-existing knowledge).

        Creates a high-strength semantic memory with origin=injected.
        """
        import uuid

        memory = Memory(
            id=str(uuid.uuid4()),
            content=content,
            memory_type=MemoryType.SEMANTIC,
            strength=0.9,
            valence=0.0,
            formed_at=datetime.now(timezone.utc),
            source_event=EventType.SYSTEM,
            metadata={"origin": "injected", "title": title or "backstory"},
        )

        if self._embedder:
            try:
                memory.embedding = await self._embedder.embed(content)
            except Exception:
                pass

        await self._storage.store_memory(memory)
        return memory

    # ── Meta-Tuning ──────────────────────────────────────────────

    async def meta_tune(
        self,
        metrics: dict[str, float],
        targets: list | None = None,
    ) -> list:
        """Run meta-controller for self-tuning parameter adjustment.

        Args:
            metrics: Current metric name → value mapping.
            targets: List of MetricTarget objects defining target ranges.

        Returns:
            List of Experiment objects (adjustments made).
        """
        from alive_memory.meta.controller import run_meta_controller

        return await run_meta_controller(
            self._storage,
            metrics,
            targets or [],
            config=self._config,
        )

    # ── Identity ─────────────────────────────────────────────────

    async def detect_drift(self) -> list:
        """Detect behavioral drift in the self-model."""
        from alive_memory.identity.drift import detect_drift
        return await detect_drift(self._storage, config=self._config)

    async def developmental_history(self) -> dict:
        """Get a summary of identity development over time."""
        from alive_memory.identity.history import summarize_development
        return await summarize_development(self._storage)
