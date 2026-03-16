"""Core type system for alive-memory.

Three-tier architecture:
  Tier 1 — DayMoment: ephemeral salient moments in SQLite
  Tier 2 — Hot Memory: markdown files on disk (journal, visitors, etc.)
  Tier 3 — Cold Memory: vector embeddings in SQLite (sleep-only)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


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
class Totem:
    """A weighted semantic association (fact, entity, concept).

    Totems store structured facts extracted during consolidation.
    Can be global (visitor_id is None) or visitor-specific.
    """
    id: str
    entity: str
    weight: float  # 0-1, importance
    visitor_id: str | None = None
    context: str = ""
    category: str = "general"
    first_seen: datetime | None = None
    last_referenced: datetime | None = None
    source_moment_id: str | None = None


@dataclass
class VisitorTrait:
    """A structured observation about a visitor.

    Traits capture specific knowledge: preferences, personality,
    demographics, relationships, etc.
    """
    id: str
    visitor_id: str
    trait_category: str  # e.g. "personal", "preference", "relationship"
    trait_key: str  # e.g. "gender_identity", "favorite_food"
    trait_value: str  # e.g. "transgender woman", "sushi"
    confidence: float = 0.5  # 0-1
    source_moment_id: str | None = None
    created_at: datetime | None = None


@dataclass
class Visitor:
    """Knowledge about a person the agent interacts with."""
    id: str
    name: str
    trust_level: str = "stranger"  # stranger → returner → regular → familiar
    visit_count: int = 1
    first_visit: datetime | None = None
    last_visit: datetime | None = None
    emotional_imprint: str = ""
    summary: str = ""


@dataclass
class RecallContext:
    """Result of a recall operation — aggregated memory context.

    Categorized results from hot memory grep and structured fact search.

    Public API fields (use these):
        episodic     — what happened (events, conversations)
        observations — notes about the user
        semantic     — general knowledge / facts
        reflections  — past reflections
        thread       — current conversation context
        entities     — structured objects / items
        traits       — user attributes / characteristics

    Legacy aliases (backward compat): journal_entries, visitor_notes,
    self_knowledge, thread_context, totem_facts, trait_facts
    """
    # Internal storage fields (used by hippocampus, adapters, etc.)
    journal_entries: list[str] = field(default_factory=list)
    visitor_notes: list[str] = field(default_factory=list)
    self_knowledge: list[str] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)
    thread_context: list[str] = field(default_factory=list)
    cold_echoes: list[str] = field(default_factory=list)
    totem_facts: list[str] = field(default_factory=list)
    trait_facts: list[str] = field(default_factory=list)
    extra_context: list[str] = field(default_factory=list)
    query: str = ""
    total_hits: int = 0

    # ── Public API aliases ────────────────────────────────────────

    @property
    def episodic(self) -> list[str]:
        """What happened — events, conversations, journal entries."""
        return self.journal_entries

    @property
    def observations(self) -> list[str]:
        """Notes about the user / visitor."""
        return self.visitor_notes

    @property
    def semantic(self) -> list[str]:
        """General knowledge, facts, self-knowledge."""
        return self.self_knowledge

    @property
    def thread(self) -> list[str]:
        """Current conversation / thread context."""
        return self.thread_context

    @property
    def entities(self) -> list[str]:
        """Structured objects, items, associations."""
        return self.totem_facts

    @property
    def traits(self) -> list[str]:
        """User attributes, characteristics, preferences."""
        return self.trait_facts

    def to_prompt(self) -> str:
        """Format recall results as clean text for LLM prompt injection.

        Produces readable text with section headers.
        Empty sections are omitted.
        """
        sections: list[str] = []
        _sections = [
            ("Recent Events", self.journal_entries),
            ("User Info", self.visitor_notes),
            ("Knowledge", self.self_knowledge),
            ("Reflections", self.reflections),
            ("Conversation", self.thread_context),
            ("Entities", self.totem_facts),
            ("Traits", self.trait_facts),
            ("Additional Context", self.extra_context),
        ]
        for title, items in _sections:
            if items:
                body = "\n".join(f"- {item}" for item in items)
                sections.append(f"### {title}\n{body}")
        if not sections:
            return ""
        return "## Relevant Context\n\n" + "\n\n".join(sections)


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
    identity_drift: dict | None = None
    duration_ms: int = 0
    depth: str = "full"
    wake_report: WakeReport | None = None


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
    last_recalled: datetime | None = None
    recall_count: int = 0
    source_event: EventType | None = None
    drive_coupling: dict[str, float] = field(default_factory=dict)
    embedding: list[float] | None = None
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
    last_sleep: datetime | None = None
    memories_total: int = 0


@dataclass
class SelfModel:
    """Persistent self-model."""
    traits: dict[str, float] = field(default_factory=dict)
    behavioral_summary: str = ""
    self_narrative: str = ""
    behavioral_signature: dict[str, Any] = field(default_factory=dict)
    relational_stance: dict[str, float] = field(default_factory=dict)
    drift_history: list[dict] = field(default_factory=list)
    version: int = 0
    snapshot_at: datetime | None = None
    narrative_version: int = 0


@dataclass
class SleepCycleReport:
    """Results from a complete sleep_cycle() orchestration."""
    # Consolidation results (from the inner consolidate() call)
    moments_consolidated: int = 0
    journal_entries_written: int = 0
    dreams_generated: int = 0
    # Meta results
    experiments_evaluated: int = 0
    parameters_adjusted: int = 0
    # Identity results
    drift_detected: bool = False
    evolution_decisions: list = field(default_factory=list)  # EvolutionDecision items
    # Wake
    wake_completed: bool = False
    # Orchestrator metadata
    phases_completed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # non-fatal errors
    duration_seconds: float = 0.0
    depth: str = "full"
