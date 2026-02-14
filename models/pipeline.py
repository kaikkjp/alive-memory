"""Typed pipeline contracts between cognitive stages.

Replaces implicit dict conventions with dataclasses so breaking changes
are caught at import/construction time, not at runtime.

Chain: cortex_call() -> CortexOutput -> validate() -> ValidatedOutput
       -> select_actions() -> MotorPlan -> execute_body() -> BodyOutput
       -> process_output() -> CycleOutput
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ActionRequest:
    """A single action requested by cortex."""
    type: str = ''
    detail: dict = field(default_factory=dict)


@dataclass
class MemoryUpdate:
    """A single memory update requested by cortex."""
    type: str = ''
    content: dict = field(default_factory=dict)


@dataclass
class DroppedAction:
    """An action that was rejected by the validator."""
    action: ActionRequest = field(default_factory=ActionRequest)
    reason: str = ''


@dataclass
class CortexOutput:
    """What comes out of the LLM call (or fallback)."""
    internal_monologue: str = ''
    dialogue: Optional[str] = None
    dialogue_language: str = 'en'
    expression: str = 'neutral'
    body_state: str = 'sitting'
    gaze: str = 'at_visitor'
    resonance: bool = False
    actions: list[ActionRequest] = field(default_factory=list)
    memory_updates: list[MemoryUpdate] = field(default_factory=list)
    next_cycle_hints: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> 'CortexOutput':
        """Construct from json.loads() output. Tolerant of missing keys."""
        actions = [
            ActionRequest(type=a.get('type', ''), detail=a.get('detail', {}))
            for a in raw.get('actions', [])
        ]
        memory_updates = [
            MemoryUpdate(type=m.get('type', ''), content=m.get('content', {}))
            for m in raw.get('memory_updates', [])
        ]
        return cls(
            internal_monologue=raw.get('internal_monologue', ''),
            dialogue=raw.get('dialogue'),
            dialogue_language=raw.get('dialogue_language', 'en'),
            expression=raw.get('expression', 'neutral'),
            body_state=raw.get('body_state', 'sitting'),
            gaze=raw.get('gaze', 'at_visitor'),
            resonance=raw.get('resonance', False),
            actions=actions,
            memory_updates=memory_updates,
            next_cycle_hints=raw.get('next_cycle_hints', []),
        )


@dataclass
class ValidatorState:
    """State context passed to the validator."""
    cycle_type: str = ''
    energy: float = 1.0
    hands_held_item: Optional[str] = None
    turn_count: int = 0
    trust_level: str = 'stranger'


@dataclass
class ValidatedOutput:
    """Post-validation output. Cortex fields + validation metadata."""

    # ── Cortex fields (copied from CortexOutput) ──
    internal_monologue: str = ''
    dialogue: Optional[str] = None
    dialogue_language: str = 'en'
    expression: str = 'neutral'
    body_state: str = 'sitting'
    gaze: str = 'at_visitor'
    resonance: bool = False
    actions: list[ActionRequest] = field(default_factory=list)
    memory_updates: list[MemoryUpdate] = field(default_factory=list)
    next_cycle_hints: list[str] = field(default_factory=list)

    # ── Validation metadata ──
    approved_actions: list[ActionRequest] = field(default_factory=list)
    dropped_actions: list[DroppedAction] = field(default_factory=list)
    journal_deferred: bool = False
    hand_warning: bool = False
    canonical_contradiction: Optional[str] = None
    voice_adjustments: list[str] = field(default_factory=list)
    entropy_warning: Optional[str] = None

    # ── Post-validation injection (set by heartbeat) ──
    focus_pool_id: Optional[str] = None

    @classmethod
    def from_cortex(cls, cortex: CortexOutput) -> 'ValidatedOutput':
        """Create ValidatedOutput from CortexOutput, copying all cortex fields."""
        return cls(
            internal_monologue=cortex.internal_monologue,
            dialogue=cortex.dialogue,
            dialogue_language=cortex.dialogue_language,
            expression=cortex.expression,
            body_state=cortex.body_state,
            gaze=cortex.gaze,
            resonance=cortex.resonance,
            actions=list(cortex.actions),
            memory_updates=list(cortex.memory_updates),
            next_cycle_hints=list(cortex.next_cycle_hints),
        )

    def to_dict(self) -> dict:
        """Convert to dict for backward compat with untyped consumers (day_memory.py)."""
        d = {
            'internal_monologue': self.internal_monologue,
            'dialogue': self.dialogue,
            'dialogue_language': self.dialogue_language,
            'expression': self.expression,
            'body_state': self.body_state,
            'gaze': self.gaze,
            'resonance': self.resonance,
            'actions': [{'type': a.type, 'detail': a.detail} for a in self.actions],
            'memory_updates': [{'type': m.type, 'content': m.content} for m in self.memory_updates],
            'next_cycle_hints': self.next_cycle_hints,
            '_approved_actions': [{'type': a.type, 'detail': a.detail} for a in self.approved_actions],
            '_dropped_actions': [
                {'action': {'type': d.action.type, 'detail': d.action.detail}, 'reason': d.reason}
                for d in self.dropped_actions
            ],
        }
        if self.focus_pool_id is not None:
            d['_focus_pool_id'] = self.focus_pool_id
        if self.journal_deferred:
            d['_journal_deferred'] = True
        if self.hand_warning:
            d['_hand_warning'] = True
        if self.canonical_contradiction:
            d['_canonical_contradiction'] = self.canonical_contradiction
        if self.voice_adjustments:
            d['_voice_adjustments'] = self.voice_adjustments
        if self.entropy_warning:
            d['_entropy_warning'] = self.entropy_warning
        return d


@dataclass
class ExecutionResult:
    """What the executor did. Returned for logging/observability."""
    events_emitted: int = 0
    actions_executed: list[str] = field(default_factory=list)
    memory_updates_processed: int = 0
    memory_update_failures: int = 0
    resonance_applied: bool = False
    pool_outcome: Optional[str] = None


# ── Body pipeline dataclasses (Phase 1) ──

@dataclass
class ActionDecision:
    """A single action after basal ganglia gating."""
    action: str = ''
    content: str = ''
    target: Optional[str] = None
    impulse: float = 1.0
    priority: float = 1.0
    status: str = 'approved'        # 'approved' | 'suppressed' | 'incapable' | 'deferred'
    suppression_reason: Optional[str] = None
    source: str = 'cortex'          # 'cortex' | 'habit'


@dataclass
class MotorPlan:
    """Basal ganglia output. Handed to Body for execution."""
    actions: list[ActionDecision] = field(default_factory=list)
    suppressed: list[ActionDecision] = field(default_factory=list)
    habit_fired: bool = False
    energy_budget: float = 1.0


@dataclass
class ActionResult:
    """Result of a single body action execution."""
    action: str = ''
    success: bool = True
    content: Optional[str] = None
    error: Optional[str] = None
    side_effects: list[str] = field(default_factory=list)
    timestamp: Optional[datetime] = None


@dataclass
class BodyOutput:
    """What the body did. Returned by execute_body()."""
    executed: list[ActionResult] = field(default_factory=list)
    energy_spent: float = 0.0
    events_emitted: int = 0


@dataclass
class CycleOutput:
    """Complete output of one cycle after output processing."""
    body_output: Optional['BodyOutput'] = None
    motor_plan: Optional['MotorPlan'] = None
    memory_updates_processed: int = 0
    memory_update_failures: int = 0
    resonance_applied: bool = False
    pool_outcome: Optional[str] = None
