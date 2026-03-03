"""Memory formation — Perception → Memory with valence and drive-coupling.

Extracted from engine/pipeline/hippocampus_write.py.
Stripped: visitor trait updates, totem creation, journal writes, thread management,
          MD file writes (all application-specific memory types).
Kept: core memory formation with valence, drive-coupling, embedding generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alive_memory.config import AliveConfig
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.intake.affect import compute_valence
from alive_memory.storage.base import BaseStorage
from alive_memory.types import (
    DriveState,
    Memory,
    MemoryType,
    MoodState,
    Perception,
)


async def form_memory(
    perception: Perception,
    mood: MoodState,
    drives: DriveState,
    storage: BaseStorage,
    *,
    embedder: EmbeddingProvider | None = None,
    config: AliveConfig | None = None,
) -> Memory:
    """Form a memory from a perception.

    Pipeline: perception → valence → drive-coupling → embedding → store

    Args:
        perception: The perception to encode as a memory.
        mood: Current mood (affects valence computation).
        drives: Current drive state (affects drive-coupling).
        storage: Storage backend for persisting the memory.
        embedder: Optional embedding provider for vector search.
        config: Configuration parameters.

    Returns:
        The formed and stored Memory.
    """
    cfg = config or AliveConfig()

    # Compute emotional valence
    valence = compute_valence(perception.content, mood)

    # Compute drive coupling (how relevant this memory is to each drive)
    coupling = _compute_drive_coupling(perception, drives)

    # Determine memory type
    memory_type = _infer_memory_type(perception)

    # Generate embedding
    embedding = None
    if embedder:
        try:
            embedding = await embedder.embed(perception.content)
        except Exception:
            pass  # embeddings are optional, degrade gracefully

    # Determine initial strength from salience
    default_strength = cfg.get("memory.default_strength", 0.5)
    strength = default_strength + (perception.salience - 0.5) * 0.4
    strength = max(0.1, min(1.0, strength))

    memory = Memory(
        id=str(uuid.uuid4()),
        content=perception.content,
        memory_type=memory_type,
        strength=strength,
        valence=valence,
        formed_at=perception.timestamp or datetime.now(timezone.utc),
        source_event=perception.event_type,
        drive_coupling=coupling,
        embedding=embedding,
        metadata=perception.metadata,
    )

    await storage.store_memory(memory)
    return memory


def _compute_drive_coupling(
    perception: Perception, drives: DriveState
) -> dict[str, float]:
    """Compute how coupled this perception is to each active drive.

    Higher drive levels make related perceptions more drive-coupled.
    Conversations couple to social drive, observations to curiosity, etc.
    """
    coupling: dict[str, float] = {}

    from alive_memory.types import EventType

    if perception.event_type == EventType.CONVERSATION:
        coupling["social"] = drives.social * 0.8
        coupling["expression"] = drives.expression * 0.3
    elif perception.event_type == EventType.OBSERVATION:
        coupling["curiosity"] = drives.curiosity * 0.7
    elif perception.event_type == EventType.ACTION:
        coupling["expression"] = drives.expression * 0.6
    else:
        # System events have weak coupling
        coupling["curiosity"] = drives.curiosity * 0.2

    return coupling


def _infer_memory_type(perception: Perception) -> MemoryType:
    """Infer memory type from perception characteristics."""
    from alive_memory.types import EventType

    if perception.event_type == EventType.CONVERSATION:
        return MemoryType.EPISODIC
    elif perception.event_type == EventType.ACTION:
        return MemoryType.PROCEDURAL
    elif perception.event_type == EventType.OBSERVATION:
        # High-salience observations become semantic, low become episodic
        if perception.salience > 0.7:
            return MemoryType.SEMANTIC
        return MemoryType.EPISODIC
    else:
        return MemoryType.SEMANTIC
