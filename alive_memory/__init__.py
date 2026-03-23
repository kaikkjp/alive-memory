"""alive-memory: Cognitive memory infrastructure for AI agents.

Usage:
    from alive_memory import AliveMemory

    async with AliveMemory(storage="agent.db") as memory:
        await memory.intake("conversation", "User said hello")
        context = await memory.recall("greetings")
        print(context.to_prompt())
"""

from __future__ import annotations

__version__ = "1.0.0a1"

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from alive_cognition.types import EventSchema

from alive_memory.clock import Clock, SystemClock
from alive_memory.config import AliveConfig
from alive_memory.consolidation.wake import WakeConfig, WakeHooks
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.embeddings.local import LocalEmbeddingProvider
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.llm.provider import LLMProvider
from alive_memory.sleep import SleepConfig
from alive_memory.storage.base import BaseStorage
from alive_memory.storage.sqlite import SQLiteStorage
from alive_memory.types import (
    CognitiveState,
    ColdEntryType,
    DayMoment,
    DriveState,
    EventType,
    MoodState,
    RecallContext,
    SelfModel,
    SleepCycleReport,
    SleepReport,
)

__all__ = [
    "AliveMemory",
    "AliveConfig",
    "RecallContext",
    "CognitiveState",
    "DayMoment",
    "DriveState",
    "EventType",
    "MoodState",
    "SelfModel",
    "SleepConfig",
    "SleepReport",
    "SleepCycleReport",
    "LLMProvider",
    "BaseStorage",
]


class _CallableLLM:
    """Wrap an async/sync callable as an LLMProvider."""

    def __init__(self, fn):
        self._fn = fn

    async def complete(self, prompt, *, system=None, max_tokens=1000, temperature=0.7):
        import inspect

        from alive_memory.llm.provider import LLMResponse

        sig = inspect.signature(self._fn)
        params = sig.parameters
        kwargs: dict[str, Any] = {}
        if "system" in params:
            kwargs["system"] = system or ""
        if "max_tokens" in params:
            kwargs["max_tokens"] = max_tokens
        if "temperature" in params:
            kwargs["temperature"] = temperature

        result = self._fn(prompt, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
        return LLMResponse(text=str(result))


def _resolve_llm(llm) -> LLMProvider | None:
    """Resolve an LLM provider from a string shorthand, callable, or pass through."""
    if llm is None or isinstance(llm, LLMProvider):
        return llm
    if callable(llm) and not isinstance(llm, str):
        return _CallableLLM(llm)
    if not isinstance(llm, str):
        return llm  # type: ignore[return-value,no-any-return]  # duck-typed provider
    name = llm.lower()
    if name == "anthropic":
        from alive_memory.llm.anthropic import AnthropicProvider

        return AnthropicProvider()
    if name == "openai":
        from alive_memory.llm.openai import OpenAIProvider

        return OpenAIProvider()
    if name == "openrouter":
        from alive_memory.llm.openrouter import OpenRouterProvider

        return OpenRouterProvider()
    if name == "gemini":
        from alive_memory.llm.gemini import GeminiProvider

        return GeminiProvider()
    raise ValueError(
        f"Unknown LLM provider {llm!r}. Use 'anthropic', 'openai', "
        f"'openrouter', 'gemini', or pass a callable/LLMProvider."
    )


class _SyncRunner:
    """Persistent event loop for sync wrappers.

    Each AliveMemory instance gets one runner. The loop stays alive
    so aiosqlite connections created during init can be reused.
    """

    def __init__(self):
        import asyncio
        import threading

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro):
        import asyncio

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def close(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


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
        visual_sources: list | None = None,
    ):
        """Initialize AliveMemory.

        Args:
            storage: A BaseStorage instance, or a string path for SQLite.
            memory_dir: Root directory for hot memory files (Tier 2).
                        If not provided, uses a temp directory.
            config: AliveConfig instance, dict, or YAML file path.
            llm: LLM provider for consolidation/reflection. Options:
                 "anthropic" — uses ANTHROPIC_API_KEY env var
                 "openai" — uses OPENAI_API_KEY env var
                 "openrouter" — uses OPENROUTER_API_KEY env var
                 A callable: async def(prompt, system="") -> str
                 An LLMProvider instance
                 Not needed for basic intake/recall.
            embedder: Embedding provider instance, or a string shorthand:
                      "openai" — uses OPENAI_API_KEY env var
                      "local" — hash-based (no API, default)
                      Defaults to LocalEmbeddingProvider if not provided.
            visual_sources: List of VisualSource objects for external visual DBs
                           (optional). Searched during recall and dreaming.
        """
        # Storage (Tier 1 + Tier 3)
        if isinstance(storage, str):
            path = storage
            if path.startswith("sqlite:///"):
                path = path[len("sqlite:///") :]
            self._storage = SQLiteStorage(path)
        else:
            self._storage = storage  # type: ignore[assignment]

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

        # Thalamus (multi-axis salience scorer)
        from alive_cognition.thalamus import Thalamus

        self._thalamus = Thalamus(config=self._config)

        # Visual sources (external visual DBs for recall/dreaming)
        self._visual_sources = visual_sources or []

        # Track previous drives for salience delta calculation
        self._prev_drives: DriveState | None = None
        self._initialized = False
        self._sync_runner: _SyncRunner | None = None

    async def initialize(self) -> None:
        """Set up storage (create tables, run migrations). Call once before use."""
        if self._initialized:
            return
        await self._storage.initialize()
        self._initialized = True

    async def close(self) -> None:
        """Release resources."""
        await self._storage.close()
        if self._sync_runner is not None:
            self._sync_runner.close()
            self._sync_runner = None
        self._initialized = False

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

        Pipeline: event → thalamus scoring → affect → drives → salience gating → DayMoment

        Args:
            event_type: Type of event (conversation, action, observation, system).
            content: The event content/text.
            metadata: Additional metadata.
            timestamp: Event time (defaults to now UTC).

        Returns:
            DayMoment if the event was salient enough to record, None otherwise.
        """
        from alive_cognition.affect import apply_affect
        from alive_cognition.drives import update_drives, update_mood
        from alive_cognition.types import EventSchema
        from alive_memory.intake.formation import form_moment

        # Normalize event_type to EventType enum
        if isinstance(event_type, EventType):
            et = event_type
        else:
            _valid = {e.value for e in EventType}
            et = EventType(event_type) if event_type in _valid else EventType.SYSTEM

        # Build structured EventSchema — use configured clock if no timestamp
        ts = timestamp or self._clock.now()
        event = EventSchema(
            event_type=et,
            content=content,
            source="chat",
            actor="user",
            timestamp=ts,
            metadata=metadata or {},
        )

        # Extract identity keywords from self-model for identity-aware salience
        identity_kws: list[str] | None = None
        try:
            self_model = await self._storage.get_self_model()
            if self_model.traits:
                identity_kws = list(self_model.traits.keys())[:10]
        except Exception:
            pass

        # Update thalamus context with current state
        mood = await self._storage.get_mood_state()
        drives = await self._storage.get_drive_state()
        self._thalamus.update_context(
            identity_keywords=identity_kws,
            current_drives=drives,
            current_mood=mood,
        )

        # Save previous drives for salience delta in formation
        self._prev_drives = DriveState(
            curiosity=drives.curiosity,
            social=drives.social,
            expression=drives.expression,
            rest=drives.rest,
        )

        # Score with thalamus (multi-axis salience)
        scored = self._thalamus.perceive(event)

        # Convert to legacy Perception for affect/drives/formation pipeline
        perception = scored.to_perception()

        # Affect lens
        perception = apply_affect(perception, mood, drives)

        # Update drives
        new_drives = update_drives(
            drives,
            [perception],
            elapsed_hours=0.0,
            config=self._config,
        )
        await self._storage.set_drive_state(new_drives)

        # Update mood
        new_mood = update_mood(
            mood,
            new_drives,
            [perception],
            elapsed_hours=0.0,
            config=self._config,
        )
        await self._storage.set_mood_state(new_mood)

        # Form moment — formation applies its own salience gating via
        # _adjust_salience, so we let it decide even for DROP-band events
        # (affect and drive deltas can still rescue borderline events).
        moment = await form_moment(
            perception,
            new_mood,
            new_drives,
            self._storage,
            previous_drives=self._prev_drives,
            config=self._config,
            clock=self._clock,
        )

        return moment

    async def intake_event(self, event: EventSchema) -> DayMoment | None:
        """Intake a structured EventSchema directly.

        Unlike intake(), this preserves all EventSchema fields (source, actor, etc.)
        for accurate salience scoring.
        """
        from alive_cognition.affect import apply_affect
        from alive_cognition.drives import update_drives, update_mood
        from alive_cognition.types import EventSchema as _ES  # noqa: F811
        from alive_memory.intake.formation import form_moment

        # Ensure timestamp uses configured clock
        if event.timestamp is None:
            event = _ES(
                event_type=event.event_type,
                content=event.content,
                source=event.source,
                actor=event.actor,
                timestamp=self._clock.now(),
                metadata=event.metadata,
            )

        # Same pipeline as intake() but with the full EventSchema
        identity_kws: list[str] | None = None
        try:
            self_model = await self._storage.get_self_model()
            if self_model.traits:
                identity_kws = list(self_model.traits.keys())[:10]
        except Exception:
            pass

        mood = await self._storage.get_mood_state()
        drives = await self._storage.get_drive_state()
        self._thalamus.update_context(
            identity_keywords=identity_kws,
            current_drives=drives,
            current_mood=mood,
        )
        self._prev_drives = DriveState(
            curiosity=drives.curiosity,
            social=drives.social,
            expression=drives.expression,
            rest=drives.rest,
        )

        scored = self._thalamus.perceive(event)
        perception = scored.to_perception()
        perception = apply_affect(perception, mood, drives)
        new_drives = update_drives(drives, [perception], elapsed_hours=0.0, config=self._config)
        await self._storage.set_drive_state(new_drives)
        new_mood = update_mood(
            mood, new_drives, [perception], elapsed_hours=0.0, config=self._config
        )
        await self._storage.set_mood_state(new_mood)

        return await form_moment(
            perception,
            new_mood,
            new_drives,
            self._storage,
            previous_drives=self._prev_drives,
            config=self._config,
            clock=self._clock,
        )

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
        visual_boundary: int | None = None,
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
            visual_boundary: Max boundary value for visual search filtering
                (e.g. current chapter number). Only visual content at or below
                this boundary is returned. None means no filtering.

        Returns:
            RecallContext with categorized results.
        """
        from alive_memory.recall.hippocampus import recall as _recall

        state = await self._storage.get_cognitive_state()
        return await _recall(
            query,
            self._reader,
            state,
            limit=limit,
            config=self._config,
            storage=self._storage,
            visitor_id=visitor_id,
            embedder=self._embedder,
            visual_sources=self._visual_sources if self._visual_sources else None,
            visual_boundary=visual_boundary,
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
        from alive_cognition.meta.controller import run_meta_controller

        return await run_meta_controller(
            self._storage,
            metrics,
            targets or [],
            config=self._config,
        )

    # ── Identity ─────────────────────────────────────────────────

    async def detect_drift(self) -> list:
        """Detect behavioral drift in the self-model."""
        from alive_cognition.identity.drift import detect_drift

        return await detect_drift(self._storage, config=self._config)

    async def developmental_history(self) -> dict:
        """Get a summary of identity development over time."""
        from alive_cognition.identity.history import summarize_development

        return await summarize_development(self._storage)

    # ── Sync Wrappers ─────────────────────────────────────────────

    def _get_sync_runner(self) -> _SyncRunner:
        """Get or create the sync runner, auto-initializing storage."""
        if self._sync_runner is None:
            self._sync_runner = _SyncRunner()
        if not self._initialized:
            self._sync_runner.run(self.initialize())
        return self._sync_runner

    def intake_sync(
        self,
        event_type: str | EventType,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> DayMoment | None:
        """Sync wrapper for intake(). Auto-initializes on first call."""
        return self._get_sync_runner().run(  # type: ignore[no-any-return]
            self.intake(event_type, content, metadata=metadata)
        )

    def recall_sync(self, query: str, *, limit: int = 10) -> RecallContext:
        """Sync wrapper for recall(). Auto-initializes on first call."""
        return self._get_sync_runner().run(self.recall(query, limit=limit))  # type: ignore[no-any-return]

    def consolidate_sync(self, *, depth: str = "full") -> SleepReport:
        """Sync wrapper for consolidate(). Auto-initializes on first call."""
        return self._get_sync_runner().run(self.consolidate(depth=depth))  # type: ignore[no-any-return]

    def sleep_sync(self) -> SleepCycleReport:
        """Sync wrapper for sleep(). Auto-initializes on first call."""
        return self._get_sync_runner().run(self.sleep())  # type: ignore[no-any-return]

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
        root = Path.home() / ".alive" / name if data_dir is None else Path(data_dir)

        root.mkdir(parents=True, exist_ok=True)

        return cls(
            storage=str(root / "memory.db"),
            memory_dir=root / "hot",
            llm=llm,
        )
