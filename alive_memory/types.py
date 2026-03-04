"""Core type system for alive-memory.

Three-tier architecture:
  Tier 1 — DayMoment: ephemeral salient moments in SQLite
  Tier 2 — Hot Memory: markdown files on disk (journal, visitors, etc.)
  Tier 3 — Cold Memory: vector embeddings in SQLite (sleep-only)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class EventType(Enum):
    CONVERSATION = "conversation"
    ACTION = "action"
    OBSERVATION = "observation"
    SYSTEM = "system"


class MemoryType(Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass
class Perception:
    """Structured perception from raw event (thalamus output)."""
    event_type: EventType
    content: str
    salience: float  # 0-1
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DayMoment:
    """Tier 1 — A salient moment recorded during the day.

    Only moments that pass the salience threshold are recorded.
    Flushed after consolidation (sleep) processes them.
    """
    id: str
    content: str
    event_type: EventType
    salience: float  # 0-1, computed deterministically
    valence: float  # -1 to 1
    drive_snapshot: dict[str, float]  # drive levels at time of moment
    timestamp: datetime
    processed: bool = False  # marked True after consolidation
    nap_processed: bool = False  # marked True after nap processes it
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallContext:
    """Result of a recall operation — aggregated hot memory context.

    Markdown-first grep over hot memory files, not vector search.
    """
    journal_entries: list[str] = field(default_factory=list)
    visitor_notes: list[str] = field(default_factory=list)
    self_knowledge: list[str] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)
    thread_context: list[str] = field(default_factory=list)
    cold_echoes: list[str] = field(default_factory=list)  # from vector search during sleep
    query: str = ""
    total_hits: int = 0


@dataclass
class WakeReport:
    """Report from a wake transition."""
    threads_managed: int = 0
    pool_items_cleaned: int = 0
    stale_moments_flushed: int = 0
    cold_embeddings_added: int = 0
    day_memory_flushed: int = 0
    duration_ms: int = 0


@dataclass
class SleepReport:
    """Report from a consolidation (sleep) cycle.

    Replaces ConsolidationReport with three-tier awareness.
    """
    moments_processed: int = 0
    journal_entries_written: int = 0
    reflections_written: int = 0
    cold_embeddings_added: int = 0
    cold_echoes_found: int = 0
    dreams: list[str] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)
    identity_drift: Optional[dict] = None
    duration_ms: int = 0
    depth: str = "full"
    wake_report: Optional[WakeReport] = None


# Keep ConsolidationReport as alias for backward compat in logs
ConsolidationReport = SleepReport


@dataclass
class Memory:
    """Legacy Memory type — kept for backward compatibility.

    New code should use DayMoment (Tier 1) and hot memory files (Tier 2).
    """
    id: str
    content: str
    memory_type: MemoryType
    strength: float  # 0-1, consolidation strength
    valence: float  # -1 to 1, emotional valence
    formed_at: datetime
    last_recalled: Optional[datetime] = None
    recall_count: int = 0
    source_event: Optional[EventType] = None
    drive_coupling: dict[str, float] = field(default_factory=dict)
    embedding: Optional[list[float]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriveState:
    """Current drive levels."""
    curiosity: float = 0.5
    social: float = 0.5
    expression: float = 0.5
    rest: float = 0.5


@dataclass
class MoodState:
    """Current mood."""
    valence: float = 0.0  # -1 to 1
    arousal: float = 0.5  # 0 to 1
    word: str = "neutral"


@dataclass
class CognitiveState:
    """Full cognitive state snapshot."""
    mood: MoodState
    energy: float
    drives: DriveState
    cycle_count: int
    last_sleep: Optional[datetime] = None
    memories_total: int = 0


@dataclass
class SelfModel:
    """Persistent self-model."""
    traits: dict[str, float] = field(default_factory=dict)
    behavioral_summary: str = ""
    drift_history: list[dict] = field(default_factory=list)
    version: int = 0
    snapshot_at: Optional[datetime] = None
