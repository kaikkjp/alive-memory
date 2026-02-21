"""sim.visitors.models — Data classes for the visitor system.

Defines VisitorArchetype (Tier 1 scripted visitors), VisitorInstance
(runtime visitor state), Visit (a single visit session), and Turn
(a single dialogue exchange).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class VisitorTier(Enum):
    """Visitor generation tier."""
    TIER_1 = 1  # Scripted archetypes
    TIER_2 = 2  # LLM-generated personas
    TIER_3 = 3  # Returning visitors (built on Tier 2)


class VisitorState(Enum):
    """Visitor state machine states."""
    ENTERING = "entering"
    BROWSING = "browsing"
    ENGAGING = "engaging"
    NEGOTIATING = "negotiating"
    DECIDING = "deciding"
    EXITING = "exiting"


class ExitReason(Enum):
    """Why a visitor left."""
    GOAL_SATISFIED = "goal_satisfied"
    PATIENCE_EXHAUSTED = "patience_exhausted"
    BUDGET_DEPLETED = "budget_depleted"
    SHOP_CLOSING = "shop_closing"
    NATURAL = "natural"
    MAX_TURNS = "max_turns"


class DayPart(Enum):
    """Time-of-day segment for arrival modulation."""
    MORNING = "morning"
    LUNCH = "lunch"
    AFTERNOON = "afternoon"
    EVENING = "evening"


# Day-part arrival rate multipliers
DAY_PART_MULTIPLIERS: dict[DayPart, float] = {
    DayPart.MORNING: 0.5,
    DayPart.LUNCH: 2.0,
    DayPart.AFTERNOON: 1.0,
    DayPart.EVENING: 0.3,
}

# Day-part boundaries as fraction of waking hours
# morning: first 20%, lunch: 20-35%, afternoon: 35-75%, evening: 75-100%
DAY_PART_BOUNDARIES: list[tuple[float, DayPart]] = [
    (0.0, DayPart.MORNING),
    (0.20, DayPart.LUNCH),
    (0.35, DayPart.AFTERNOON),
    (0.75, DayPart.EVENING),
]


@dataclass
class VisitorArchetype:
    """Tier 1 scripted visitor template.

    Defines personality traits and dialogue templates for deterministic
    visitor behavior without LLM calls.
    """
    archetype_id: str
    name: str
    traits: VisitorTraits
    goal_templates: list[str] = field(default_factory=list)
    dialogue_templates: dict[str, list[str]] = field(default_factory=dict)
    weight: float = 1.0  # Selection weight for random archetype picking


@dataclass
class VisitorTraits:
    """Personality trait vector for a visitor."""
    patience: float = 0.5       # 0-1, maps to max_turns before leaving
    knowledge: float = 0.5      # 0-1, TCG expertise level
    budget: float = 0.5         # 0-1, spending willingness
    chattiness: float = 0.5     # 0-1, dialogue length tendency
    collector_bias: float = 0.0  # 0-1, preference for rare/vintage
    emotional_state: str = "neutral"


@dataclass
class ReturnPlan:
    """Whether and when a visitor plans to return."""
    will_return: bool = False
    probability: float = 0.0
    horizon: str = "medium"  # "short" | "medium" | "long"
    min_cycles: int = 200
    max_cycles: int = 400


@dataclass
class VisitorInstance:
    """Runtime state of a specific visitor.

    Tracks a visitor across visits, including return scheduling
    and memory stubs for Tier 3.
    """
    visitor_id: str
    tier: VisitorTier
    archetype_id: str | None = None     # Tier 1 only
    persona_text: str | None = None     # Tier 2 only (LLM-generated)
    name: str = "Visitor"
    traits: VisitorTraits = field(default_factory=VisitorTraits)
    visit_history: list[VisitSummary] = field(default_factory=list)
    memory_stub: str | None = None      # What they remember from last visit
    return_plan: ReturnPlan = field(default_factory=ReturnPlan)
    goal: str = "browse"


@dataclass
class VisitSummary:
    """Summary of a completed visit, stored on the visitor instance."""
    visit_id: str
    start_cycle: int
    end_cycle: int
    exit_reason: str
    turns: int
    shopkeeper_recalled: bool = False


@dataclass
class Turn:
    """A single dialogue exchange within a visit."""
    speaker: str           # "visitor" | "shopkeeper"
    text: str
    intent: str = ""       # What the visitor was trying to do
    outcome: str = ""      # Result of the exchange


@dataclass
class Visit:
    """A complete visit session.

    Tracks the full lifecycle of a visitor's time in the shop,
    from arrival to departure.
    """
    visit_id: str
    visitor_id: str
    start_cycle: int
    end_cycle: int = -1
    scenario: str = "standard"
    day_part: DayPart = DayPart.AFTERNOON
    turns: list[Turn] = field(default_factory=list)
    exit_reason: ExitReason = ExitReason.NATURAL
    shopkeeper_recalled_visitor: bool = False

    @property
    def duration_cycles(self) -> int:
        if self.end_cycle < 0:
            return 0
        return self.end_cycle - self.start_cycle

    @property
    def turn_count(self) -> int:
        return len(self.turns)


@dataclass
class ScheduledArrival:
    """An arrival event produced by the Poisson scheduler.

    Contains all information needed to inject a visitor_connect +
    visitor_speech sequence into the runner.
    """
    cycle: int
    visitor: VisitorInstance
    day_part: DayPart
    visit_duration_cycles: int  # Expected visit length
