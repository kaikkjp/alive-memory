from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class RoomState:
    time_of_day: str = 'morning'        # morning | afternoon | evening | night
    weather: str = 'clear'
    shop_status: str = 'open'           # open | closed | resting
    ambient_music: Optional[str] = None
    room_arrangement: dict = field(default_factory=dict)
    updated_at: Optional[datetime] = None


# ── Epistemic Curiosity (TASK-043) ──

EPISTEMIC_CONFIG = {
    'max_active': 5,
    'creation_threshold': 0.08,
    'merge_similarity': 0.80,
    'decay_rate_default': 0.02,
    'reinforcement_boost': 0.10,
    'resolution_mood_bump': 0.08,
    'eviction_policy': 'lowest_intensity',
}


@dataclass
class EpistemicCuriosity:
    """A specific question she's actively wondering about.

    Lifecycle: born from gap detection (partial match with thread/totem),
    reinforced by related content, decays when unfed, resolved when answered.
    """
    id: str = ''
    topic: str = ''                     # "1991 Bandai prism card variants"
    question: str = ''                  # "Are there more variants I haven't seen?"
    intensity: float = 0.5             # 0.0 to 1.0
    source_type: str = ''              # "notification", "visitor", "journal_reflection"
    source_id: str = ''
    created_at: str = ''               # ISO timestamp
    last_reinforced_at: str = ''
    decay_rate_per_hour: float = 0.02  # configurable per question
    resolved: bool = False
    resolution_source: Optional[str] = None


@dataclass
class DrivesState:
    social_hunger: float = 0.5
    curiosity: float = 0.5             # TASK-043: this IS diversive_curiosity (field kept for compat)
    expression_need: float = 0.3
    rest_need: float = 0.2
    energy: float = 0.8
    mood_valence: float = 0.0           # -1 (dark) to +1 (bright)
    mood_arousal: float = 0.3           # 0 (still) to 1 (activated)
    updated_at: Optional[datetime] = None

    # TASK-043: 'diversive_curiosity' aliases 'curiosity' field.
    # New code should prefer diversive_curiosity for clarity.
    # The underlying field is 'curiosity' so all existing constructor calls,
    # DB reads, and attribute access continue to work unchanged.
    @property
    def diversive_curiosity(self) -> float:
        return self.curiosity

    @diversive_curiosity.setter
    def diversive_curiosity(self, value: float):
        self.curiosity = value

    def copy(self) -> 'DrivesState':
        return DrivesState(
            social_hunger=self.social_hunger,
            curiosity=self.curiosity,
            expression_need=self.expression_need,
            rest_need=self.rest_need,
            energy=self.energy,
            mood_valence=self.mood_valence,
            mood_arousal=self.mood_arousal,
            updated_at=self.updated_at,
        )


@dataclass
class EngagementState:
    status: str = 'none'                # none | engaged | cooldown
    visitor_id: Optional[str] = None
    context_id: Optional[str] = None
    started_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    turn_count: int = 0

    def is_engaged_with(self, source: str) -> bool:
        if self.status != 'engaged':
            return False
        vid = source.split(':')[1] if ':' in source else source
        return self.visitor_id == vid


@dataclass
class VisitorPresence:
    """A visitor currently in the shop (multi-slot presence model)."""
    visitor_id: str
    status: str = 'browsing'            # browsing | in_conversation | waiting | left
    entered_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    connection_type: str = 'tcp'        # tcp | websocket


@dataclass
class Visitor:
    id: str
    name: Optional[str] = None
    trust_level: str = 'stranger'       # stranger | returner | regular | familiar
    visit_count: int = 0
    first_visit: Optional[datetime] = None
    last_visit: Optional[datetime] = None
    summary: Optional[str] = None
    emotional_imprint: Optional[str] = None
    hands_state: Optional[str] = None


@dataclass
class VisitorTrait:
    id: str
    visitor_id: str
    trait_category: str                 # taste | personality | topic | relationship
    trait_key: str
    trait_value: str
    observed_at: datetime
    source_event_id: str
    confidence: float = 0.5
    stability: float = 0.2
    status: str = 'active'             # active | anomaly | archived
    notes: Optional[str] = None


@dataclass
class Totem:
    id: str
    entity: str                         # "Nujabes", "rain photograph", etc.
    weight: float = 0.5                 # 0-1, emotional importance
    visitor_id: Optional[str] = None
    context: Optional[str] = None       # "first_gift", "mentioned_in_passing"
    category: Optional[str] = None      # music | visual | quote | concept | person
    first_seen: Optional[datetime] = None
    last_referenced: Optional[datetime] = None
    source_event_id: Optional[str] = None


@dataclass
class CollectionItem:
    id: str
    item_type: str                      # music | image | quote | link | object
    title: str
    url: Optional[str] = None
    description: Optional[str] = None
    location: str = 'shelf'             # shelf | counter | backroom | declined
    origin: str = 'appeared'            # found | gift | appeared | created
    gifted_by: Optional[str] = None
    her_feeling: Optional[str] = None
    emotional_tags: list = field(default_factory=list)
    display_note: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class JournalEntry:
    id: str
    content: str
    mood: Optional[str] = None
    day_alive: Optional[int] = None
    tags: list = field(default_factory=list)
    created_at: Optional[datetime] = None


@dataclass
class DailySummary:
    """Lightweight daily summary index.

    After TASK-007, daily summaries are indices (moment count, moment IDs,
    journal entry IDs, emotional arc) — not concatenated narratives.
    Individual reflections are stored as separate journal entries.
    """
    id: str
    day_number: Optional[int] = None
    date: Optional[str] = None
    moment_count: int = 0
    moment_ids: list = field(default_factory=list)
    journal_entry_ids: list = field(default_factory=list)
    emotional_arc: Optional[str] = None
    notable_totems: list = field(default_factory=list)
    created_at: Optional[datetime] = None


@dataclass
class Thread:
    id: str
    thread_type: str                    # question | project | anticipation | unresolved | ritual
    title: str
    status: str = 'open'               # open | active | dormant | archived | closed
    priority: float = 0.5
    content: Optional[str] = None      # her current thinking
    resolution: Optional[str] = None   # how it ended (if closed)
    created_at: Optional[datetime] = None
    last_touched: Optional[datetime] = None
    touch_count: int = 0
    touch_reason: Optional[str] = None
    target_date: Optional[str] = None
    source_visitor_id: Optional[str] = None
    source_event_id: Optional[str] = None
    tags: list = field(default_factory=list)


# ── TASK-100: Idle Arc phase function ──

def idle_phase(idle_streak: int) -> str:
    """Map consecutive idle count to phase: DEEPEN, WANDER, or STILL."""
    if idle_streak <= 20:
        return 'DEEPEN'
    elif idle_streak <= 40:
        return 'WANDER'
    return 'STILL'


def idle_cycle_multiplier(idle_streak: int) -> float:
    """Return cycle interval multiplier for current idle streak.

    DEEPEN/WANDER: 1.0x (normal), STILL early (41-60): 2.0x, STILL deep (61+): 4.0x.
    """
    phase = idle_phase(idle_streak)
    if phase != 'STILL':
        return 1.0
    if idle_streak <= 60:
        return 2.0
    return 4.0
