"""alive-memory: Cognitive memory layer for persistent AI characters.

Three-tier memory architecture:
  Tier 1 — Day Memory: ephemeral salient moments in SQLite
  Tier 2 — Hot Memory: markdown files on disk (journal, visitors, etc.)
  Tier 3 — Cold Memory: vector embeddings in SQLite (sleep-only)

Usage:
    from alive_memory import AliveMemory

    memory = AliveMemory(storage="memory.db", memory_dir="/data/agent/memory")
    await memory.initialize()

    # Record an event (may or may not become a moment)
    moment = await memory.intake(event_type="conversation", content="Hello world")

    # Recall from hot memory
    context = await memory.recall(query="greetings")

    # Consolidate (sleep)
    report = await memory.consolidate()
"""

from __future__ import annotations

__version__ = "0.3.0"

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alive_memory.clock import Clock, SystemClock
from alive_memory.config import AliveConfig
from alive_memory.consolidation.wake import WakeConfig, WakeHooks
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.embeddings.local import LocalEmbeddingProvider
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.translator import (
    scrub_numbers,
    translate_drives_summary,
    translate_mood,
)
from alive_memory.hot.writer import MemoryWriter
from alive_memory.llm.provider import LLMProvider
from alive_memory.sleep import SleepConfig, nap, sleep_cycle
from alive_memory.storage.base import BaseStorage
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import (
    CognitiveState,
    ConsolidationReport,
    DayMoment,
    DriveState,
    EventType,
    Memory,
    MemoryType,
    MoodState,
    Perception,
    RecallContext,
    SelfModel,
    SleepCycleReport,
    SleepReport,
    Totem,
    Visitor,
    VisitorTrait,
    WakeReport,
)

__all__ = [
    "AliveMemory",
    "AliveConfig",
    "BaseStorage",
    "SQLiteStorage",
    "LLMProvider",
    "EmbeddingProvider",
    "MemoryReader",
    "MemoryWriter",
    "CognitiveState",
    "ConsolidationReport",
    "DayMoment",
    "DriveState",
    "EventType",
    "Memory",
    "MemoryType",
    "MoodState",
    "Perception",
    "RecallContext",
    "SelfModel",
    "SleepConfig",
    "SleepCycleReport",
    "SleepReport",
    "WakeConfig",
    "WakeHooks",
    "Totem",
    "Visitor",
    "VisitorTrait",
    "WakeReport",
    "nap",
    "scrub_numbers",
    "sleep_cycle",
    "translate_drives_summary",
    "translate_mood",
]


def _resolve_llm(llm: LLMProvider | str | None) -> LLMProvider | None:
    """Resolve an LLM provider from a string shorthand or pass through."""
    if llm is None or isinstance(llm, LLMProvider):
        return llm
    if not isinstance(llm, str):
        return llm  # duck-typed provider
    name = llm.lower()
    if name == "anthropic":
        from alive_memory.llm.anthropic import AnthropicProvider
        return AnthropicProvider()
    if name == "openrouter":
        from alive_memory.llm.openrouter import OpenRouterProvider
        return OpenRouterProvider()
    if name == "gemini":
        from alive_memory.llm.gemini import GeminiProvider
        return GeminiProvider()
    raise ValueError(
        f"Unknown LLM provider {llm!r}. Use 'anthropic', 'openrouter', "
        f"'gemini', or pass an LLMProvider instance."
    )


def _resolve_embedder(
    embedder: EmbeddingProvider | str | None, default_dims: int
) -> EmbeddingProvider:
    """Resolve an embedding provider from a string shorthand or pass through."""
    if embedder is None or (isinstance(embedder, str) and embedder.lower() == "local"):
        return LocalEmbeddingProvider(dimensions=default_dims)
    if isinstance(embedder, str):
        name = embedder.lower()
        if name == "openai":
            from alive_memory.embeddings.api import OpenAIEmbeddingProvider
            return OpenAIEmbeddingProvider()
        raise ValueError(
            f"Unknown embedding provider {embedder!r}. Use 'openai', 'local', "
            f"or pass an EmbeddingProvider instance."
        )
    return embedder


class AliveMemory:
    """Public API for the alive-memory cognitive memory layer.

    Three-tier architecture:
      - intake() records salient moments to day memory (Tier 1)
      - recall() greps hot memory markdown files (Tier 2)
      - consolidate() processes moments → writes journal/reflections → embeds to cold (Tier 3)
    """

    def __init__(
        self,
        storage: BaseStorage | str = "memory.db",
        *,
        memory_dir: str | Path | None = None,
        config: AliveConfig | dict | str | None = None,
        llm: LLMProvider | str | None = None,
        embedder: EmbeddingProvider | str | None = None,
        clock: Clock | None = None,
    ):
        """Initialize AliveMemory.

        Args:
            storage: A BaseStorage instance, or a string path for SQLite.
            memory_dir: Root directory for hot memory files (Tier 2).
                        If not provided, uses a temp directory.
            config: AliveConfig instance, dict, or YAML file path.
            llm: LLM provider instance, or a string shorthand:
                 "anthropic" — uses ANTHROPIC_API_KEY env var
                 "openrouter" — uses OPENROUTER_API_KEY env var
                 Needed for consolidation reflection/dreaming.
            embedder: Embedding provider instance, or a string shorthand:
                      "openai" — uses OPENAI_API_KEY env var
                      "local" — hash-based (no API, default)
                      Defaults to LocalEmbeddingProvider if not provided.
        """
        # Storage (Tier 1 + Tier 3)
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
        self._llm = _resolve_llm(llm)

        # Embedder (default to local hash-based)
        self._embedder = _resolve_embedder(
            embedder, self._config.get("memory.embedding_dimensions", 384)
        )

        # Hot memory (Tier 2)
        if memory_dir is None:
            self._memory_dir = Path(tempfile.mkdtemp(prefix="alive_memory_"))
        else:
            self._memory_dir = Path(memory_dir)

        self._writer = MemoryWriter(self._memory_dir)
        self._reader = MemoryReader(self._memory_dir)

        # Clock
        self._clock = clock or SystemClock()

        # Track previous drives for salience delta calculation
        self._prev_drives: DriveState | None = None

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

    # ── Properties ────────────────────────────────────────────────

    @property
    def storage(self) -> BaseStorage:
        """Access the underlying storage backend."""
        return self._storage

    @property
    def writer(self) -> MemoryWriter:
        """Access the hot memory writer."""
        return self._writer

    @property
    def reader(self) -> MemoryReader:
        """Access the hot memory reader."""
        return self._reader

    @property
    def memory_dir(self) -> Path:
        """Root directory for hot memory files."""
        return self._memory_dir

    # ── Intake ───────────────────────────────────────────────────

    async def intake(
        self,
        event_type: str | EventType,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> DayMoment | None:
        """Record an event. Returns a DayMoment if salient enough, None otherwise.

        Pipeline: event → perception → affect → drives → salience gating → DayMoment

        Args:
            event_type: Type of event (conversation, action, observation, system).
            content: The event content/text.
            metadata: Additional metadata.
            timestamp: Event time (defaults to now UTC).

        Returns:
            DayMoment if the event was salient enough to record, None otherwise.
        """
        from alive_memory.intake.affect import apply_affect
        from alive_memory.intake.drives import update_drives, update_mood
        from alive_memory.intake.formation import form_moment
        from alive_memory.intake.thalamus import perceive

        # Step 1: Perceive
        perception = perceive(
            event_type, content,
            config=self._config,
            metadata=metadata,
            timestamp=timestamp,
            clock=self._clock,
        )

        # Step 2: Affect lens
        mood = await self._storage.get_mood_state()
        drives = await self._storage.get_drive_state()

        # Save previous drives for salience delta
        self._prev_drives = DriveState(
            curiosity=drives.curiosity,
            social=drives.social,
            expression=drives.expression,
            rest=drives.rest,
        )

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

        # Step 5: Form moment (salience gating)
        moment = await form_moment(
            perception, new_mood, new_drives, self._storage,
            previous_drives=self._prev_drives,
            config=self._config,
            clock=self._clock,
        )

        return moment

    # ── Media Intake ─────────────────────────────────────────────

    async def intake_media(
        self,
        file_path: str | Path,
        *,
        media_llm: object | None = None,
        event_type: str | EventType = EventType.OBSERVATION,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DayMoment | None:
        """Ingest a media file (image, audio, video, PDF) into memory.

        Uses a multimodal LLM (default: Gemini) to perceive the media,
        then feeds the text description through the standard intake pipeline.

        Args:
            file_path: Path to the media file.
            media_llm: A provider with perceive_media() (e.g. GeminiProvider).
                       Falls back to self._llm if it supports perceive_media().
            event_type: Event type for the resulting moment (default: observation).
            prompt: Custom perception prompt for the LLM.
            metadata: Additional metadata to attach.

        Returns:
            DayMoment if salient enough, None otherwise.

        Raises:
            RuntimeError: If no multimodal-capable LLM is available.
        """
        from alive_memory.intake.multimodal import perceive_media

        provider = media_llm or self._llm
        if provider is None or not hasattr(provider, "perceive_media"):
            raise RuntimeError(
                "intake_media() requires a multimodal LLM with perceive_media(). "
                "Pass media_llm=GeminiProvider(...) or set llm='gemini' on AliveMemory."
            )

        text = await perceive_media(file_path, provider, prompt=prompt)

        meta = metadata or {}
        meta["media_source"] = str(file_path)
        meta["media_perceived"] = True

        return await self.intake(
            event_type=event_type,
            content=text,
            metadata=meta,
        )

    # ── Recall ───────────────────────────────────────────────────

    async def recall(
        self,
        query: str,
        *,
        limit: int = 10,
        visitor_id: str | None = None,
    ) -> RecallContext:
        """Retrieve context relevant to a query from memory.

        When visitor_id is provided (or detected from the query), does
        direct ID-based lookups for visitor profile, totems, and traits.
        Falls back to keyword grep + search for open-ended queries.

        Args:
            query: Search query text.
            limit: Maximum results per category.
            visitor_id: Known visitor ID for direct lookups (optional).
                If not provided, attempts to identify visitor from query.

        Returns:
            RecallContext with categorized results.
        """
        from alive_memory.recall.hippocampus import recall as _recall

        state = await self._storage.get_cognitive_state()
        return await _recall(
            query, self._reader, state,
            limit=limit,
            config=self._config,
            storage=self._storage,
            visitor_id=visitor_id,
        )

    # ── Consolidation ────────────────────────────────────────────

    async def consolidate(
        self,
        *,
        whispers: list[dict] | None = None,
        depth: str = "full",
        wake_hooks: WakeHooks | None = None,
        wake_config: WakeConfig | None = None,
    ) -> SleepReport:
        """Run memory consolidation (sleep).

        Full pipeline:
          1. Get unprocessed day moments
          2. Per moment: gather context → cold search → LLM reflect → write to hot memory
          3. Daily summary → batch embed to cold → flush day_memory
          4. (optional) Wake transition if *wake_hooks* provided

        Args:
            whispers: Config changes to process as dream perceptions.
            depth: "full" for complete consolidation, "nap" for light.
            wake_hooks: Optional WakeHooks protocol implementation.
            wake_config: Optional WakeConfig for the wake transition.

        Returns:
            SleepReport with statistics.
        """
        from alive_memory.consolidation import consolidate as _consolidate

        return await _consolidate(
            self._storage,
            writer=self._writer,
            reader=self._reader,
            llm=self._llm,
            embedder=self._embedder,
            config=self._config,
            whispers=whispers,
            depth=depth,
            wake_hooks=wake_hooks,
            wake_config=wake_config,
        )

    # ── State ────────────────────────────────────────────────────

    async def get_state(self) -> CognitiveState:
        """Get the current cognitive state."""
        return await self._storage.get_cognitive_state()

    async def get_identity(self) -> SelfModel:
        """Get the current self-model."""
        return await self._storage.get_self_model()

    # ── Drive Management ─────────────────────────────────────────

    _VALID_DRIVES = frozenset({"curiosity", "social", "expression", "rest"})

    async def update_drive(self, drive: str, delta: float) -> DriveState:
        """Manually adjust a drive value.

        Args:
            drive: Drive name (curiosity, social, expression, rest).
            delta: Change amount (positive or negative).

        Returns:
            Updated DriveState.

        Raises:
            ValueError: If drive name is not a known drive field.
        """
        if drive not in self._VALID_DRIVES:
            raise ValueError(
                f"Unknown drive {drive!r}, must be one of {sorted(self._VALID_DRIVES)}"
            )
        drives = await self._storage.get_drive_state()
        current = getattr(drives, drive)
        setattr(drives, drive, max(0.0, min(1.0, current + delta)))
        await self._storage.set_drive_state(drives)
        return drives

    # ── Backstory Injection ──────────────────────────────────────

    async def inject_backstory(
        self,
        content: str,
        *,
        title: str | None = None,
    ) -> DayMoment:
        """Inject a backstory as a high-salience moment + self-knowledge file.

        Creates a DayMoment with max salience and writes to self/ directory.
        """
        import uuid

        moment = DayMoment(
            id=str(uuid.uuid4()),
            content=content,
            event_type=EventType.SYSTEM,
            salience=1.0,
            valence=0.0,
            drive_snapshot={"curiosity": 0.5, "social": 0.5, "expression": 0.5, "rest": 0.5},
            timestamp=datetime.now(UTC),
            metadata={"origin": "injected", "title": title or "backstory"},
        )

        await self._storage.record_moment(moment)

        # Also write to self-knowledge
        filename = title or "backstory"
        self._writer.write_self_file(filename, f"# {filename}\n\n{content}\n")

        return moment

    # ── Sleep Cycle ──────────────────────────────────────────────

    async def sleep(
        self, *, sleep_config: SleepConfig | None = None, **kwargs: Any
    ) -> SleepCycleReport:
        """Run the full sleep cycle orchestrator.

        Raises:
            RuntimeError: If no LLM provider is configured.
        """
        if self._llm is None:
            raise RuntimeError(
                "sleep() requires an LLM provider. Pass llm='anthropic' or "
                "llm='openrouter' to AliveMemory(), or provide an LLMProvider instance."
            )
        from alive_memory.sleep import sleep_cycle

        return await sleep_cycle(
            self._storage,
            self._writer,
            self._reader,
            self._llm,
            embedder=self._embedder,
            config=self._config,
            sleep_config=sleep_config,
            **kwargs,
        )

    # ── Meta-Tuning ──────────────────────────────────────────────

    async def meta_tune(
        self,
        metrics: dict[str, float],
        targets: list | None = None,
    ) -> list:
        """Run meta-controller for self-tuning parameter adjustment."""
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

    # ── Autotune ─────────────────────────────────────────────────

    async def autotune(
        self,
        budget: int = 50,
        scenarios: str = "builtin",
        *,
        scoring_weights: dict | None = None,
        verbose: bool = True,
    ) -> Any:
        """Run parameter auto-tuning.

        Args:
            budget: Number of iterations.
            scenarios: "builtin" or path to custom scenario directory.
            scoring_weights: Override default MemoryScore weights.
            verbose: Print progress during tuning.

        Returns:
            AutotuneResult with best_config, experiment_log, and report.
        """
        from alive_memory.autotune import AutotuneConfig
        from alive_memory.autotune import autotune as _autotune

        result = await _autotune(
            config=self._config,
            autotune_config=AutotuneConfig(
                budget=budget,
                scenarios=scenarios,
                scoring_weights=scoring_weights,
                verbose=verbose,
            ),
        )
        return result

    def apply_tuned_config(self, result: Any) -> None:
        """Apply an AutotuneResult's best config to this instance."""
        for key, value in result.best_config.items():
            self._config.set(key, value)

    # ── Quickstart ────────────────────────────────────────────────

    @classmethod
    def quickstart(
        cls,
        name: str = "agent",
        *,
        llm: LLMProvider | str | None = None,
        data_dir: str | Path | None = None,
    ) -> AliveMemory:
        """Create an AliveMemory instance with sensible defaults.

        Zero-config convenience constructor. Stores data in
        ~/.alive/{name}/ with SQLite + local embeddings.

        Args:
            name: Agent name (used for data directory).
            llm: Optional LLM provider for consolidation.
                 Pass "anthropic", "openrouter", "gemini", or an instance.
            data_dir: Override the data directory (default: ~/.alive/{name}).

        Returns:
            An AliveMemory instance (call .initialize() or use as async context manager).

        Usage:
            async with AliveMemory.quickstart("my-agent") as memory:
                await memory.intake(event_type="conversation", content="Hello!")
                context = await memory.recall("hello")
        """
        if data_dir is None:
            root = Path.home() / ".alive" / name
        else:
            root = Path(data_dir)

        root.mkdir(parents=True, exist_ok=True)

        return cls(
            storage=str(root / "memory.db"),
            memory_dir=root / "hot",
            llm=llm,
        )
