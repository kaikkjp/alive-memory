"""Pydantic v2 request/response models for the alive-memory REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from alive_memory.types import (
    CognitiveState,
    DayMoment,
    DriveState,
    RecallContext,
    SelfModel,
    SleepReport,
)

# ── Request Models ────────────────────────────────────────────────


class IntakeRequest(BaseModel):
    """POST /intake"""

    event_type: str = Field(description="Event type: conversation, action, observation, system")
    content: str = Field(description="Event content text")
    metadata: dict[str, Any] | None = None
    timestamp: datetime | None = None


class RecallRequest(BaseModel):
    """POST /recall"""

    query: str = Field(description="Search query text (keywords)")
    limit: int = Field(default=10, ge=1, le=100)


class ConsolidateRequest(BaseModel):
    """POST /consolidate"""

    whispers: list[dict[str, Any]] | None = None
    depth: str = Field(default="full", pattern="^(full|nap)$")


class DriveUpdateRequest(BaseModel):
    """POST /drives/{name}"""

    delta: float = Field(description="Change amount (positive or negative)", ge=-1.0, le=1.0)


class BackstoryRequest(BaseModel):
    """POST /backstory"""

    content: str = Field(description="Backstory content text")
    title: str | None = None


# ── Response Models ───────────────────────────────────────────────


class DayMomentResponse(BaseModel):
    """A single day moment (Tier 1)."""

    id: str
    content: str
    event_type: str
    salience: float
    valence: float
    drive_snapshot: dict[str, float] = Field(default_factory=dict)
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallContextResponse(BaseModel):
    """Recall results from hot memory (Tier 2) and structured facts."""

    journal_entries: list[str] = Field(default_factory=list)
    visitor_notes: list[str] = Field(default_factory=list)
    self_knowledge: list[str] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)
    thread_context: list[str] = Field(default_factory=list)
    totem_facts: list[str] = Field(default_factory=list)
    trait_facts: list[str] = Field(default_factory=list)
    query: str = ""
    total_hits: int = 0


class MoodResponse(BaseModel):
    valence: float
    arousal: float
    word: str


class DriveStateResponse(BaseModel):
    curiosity: float
    social: float
    expression: float
    rest: float


class CognitiveStateResponse(BaseModel):
    mood: MoodResponse
    energy: float
    drives: DriveStateResponse
    cycle_count: int
    last_sleep: datetime | None = None
    memories_total: int = 0


class SelfModelResponse(BaseModel):
    traits: dict[str, float] = Field(default_factory=dict)
    behavioral_summary: str = ""
    drift_history: list[dict[str, Any]] = Field(default_factory=list)
    version: int = 0
    snapshot_at: datetime | None = None


class SleepReportResponse(BaseModel):
    moments_processed: int = 0
    journal_entries_written: int = 0
    reflections_written: int = 0
    cold_embeddings_added: int = 0
    cold_echoes_found: int = 0
    dreams: list[str] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)
    identity_drift: dict[str, Any] | None = None
    duration_ms: int = 0
    depth: str = "full"


# Keep old name as alias
ConsolidationReportResponse = SleepReportResponse


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = ""


# ── Converters (dataclass → Pydantic) ────────────────────────────


def moment_to_response(moment: DayMoment) -> DayMomentResponse:
    """Convert a DayMoment dataclass to DayMomentResponse."""
    return DayMomentResponse(
        id=moment.id,
        content=moment.content,
        event_type=moment.event_type.value,
        salience=moment.salience,
        valence=moment.valence,
        drive_snapshot=moment.drive_snapshot,
        timestamp=moment.timestamp,
        metadata=moment.metadata,
    )


def recall_context_to_response(ctx: RecallContext) -> RecallContextResponse:
    """Convert a RecallContext dataclass to RecallContextResponse."""
    return RecallContextResponse(
        journal_entries=ctx.journal_entries,
        visitor_notes=ctx.visitor_notes,
        self_knowledge=ctx.self_knowledge,
        reflections=ctx.reflections,
        thread_context=ctx.thread_context,
        totem_facts=ctx.totem_facts,
        trait_facts=ctx.trait_facts,
        query=ctx.query,
        total_hits=ctx.total_hits,
    )


def cognitive_state_to_response(state: CognitiveState) -> CognitiveStateResponse:
    return CognitiveStateResponse(
        mood=MoodResponse(
            valence=state.mood.valence,
            arousal=state.mood.arousal,
            word=state.mood.word,
        ),
        energy=state.energy,
        drives=DriveStateResponse(
            curiosity=state.drives.curiosity,
            social=state.drives.social,
            expression=state.drives.expression,
            rest=state.drives.rest,
        ),
        cycle_count=state.cycle_count,
        last_sleep=state.last_sleep,
        memories_total=state.memories_total,
    )


def self_model_to_response(model: SelfModel) -> SelfModelResponse:
    return SelfModelResponse(
        traits=model.traits,
        behavioral_summary=model.behavioral_summary,
        drift_history=model.drift_history,
        version=model.version,
        snapshot_at=model.snapshot_at,
    )


def drive_state_to_response(drives: DriveState) -> DriveStateResponse:
    return DriveStateResponse(
        curiosity=drives.curiosity,
        social=drives.social,
        expression=drives.expression,
        rest=drives.rest,
    )


def sleep_report_to_response(report: SleepReport) -> SleepReportResponse:
    return SleepReportResponse(
        moments_processed=report.moments_processed,
        journal_entries_written=report.journal_entries_written,
        reflections_written=report.reflections_written,
        cold_embeddings_added=report.cold_embeddings_added,
        cold_echoes_found=report.cold_echoes_found,
        dreams=report.dreams,
        reflections=report.reflections,
        identity_drift=report.identity_drift,
        duration_ms=report.duration_ms,
        depth=report.depth,
    )


# Keep old name as alias
consolidation_report_to_response = sleep_report_to_response
