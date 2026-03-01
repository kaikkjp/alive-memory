"""Hypothalamus — drives math. Deterministic. No LLM."""

import time
from dataclasses import dataclass

from models.event import Event
from models.state import DrivesState, EpistemicCuriosity, EPISTEMIC_CONFIG
from db.parameters import p, p_or
from alive_config import cfg
import db as _db


# ── Session Tracker (TASK-105) ──
# Tracks per-visitor conversation sessions for diminishing social relief.
# A "session" is a burst of conversation with gaps < 10 minutes.
# Not persisted — resets on restart, which is fine (sessions are transient).

@dataclass
class _Session:
    count: int = 0
    last_message_at: float = 0.0


class _SessionTracker:
    def __init__(self):
        self.sessions: dict[str, _Session] = {}

    def on_message(self, visitor_id: str) -> int:
        """Record a message and return the session message count."""
        now = time.time()
        session = self.sessions.get(visitor_id)
        if session is None or (now - session.last_message_at) > 600:  # 10 min timeout
            self.sessions[visitor_id] = _Session(count=1, last_message_at=now)
            return 1
        session.count += 1
        session.last_message_at = now
        return session.count


_session_tracker = _SessionTracker()

# ── HOTFIX-002: Valence death spiral prevention ──
# All constants loaded from alive_config.yaml via cfg()
VALENCE_HARD_FLOOR = cfg('hypothalamus.valence_hard_floor', -0.85)
MAX_VALENCE_DELTA_PER_CYCLE = cfg('hypothalamus.max_valence_delta_per_cycle', 0.10)
VALENCE_EQUILIBRIUM = cfg('hypothalamus.valence_equilibrium', 0.05)


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _homeostatic_pull(current: float, equilibrium: float,
                      elapsed_hours: float,
                      lo: float = 0.0, hi: float = 1.0) -> float:
    """Pull a drive toward its equilibrium point.

    Proportional spring: further from equilibrium = stronger pull.
    At extremes (distance > 0.5), spring is exponential — like a rubber
    band that gets much stronger the further you stretch it. This prevents
    valence death spirals where negative mood self-reinforces via dark
    context (HOTFIX-002).

    Near equilibrium, pull vanishes, letting natural variation emerge.
    """
    distance = abs(equilibrium - current)
    base_delta = (equilibrium - current) * p('hypothalamus.homeostatic_pull_rate') * elapsed_hours
    spring_distance = cfg('hypothalamus.exponential_spring_distance', 0.5)
    spring_multiplier = cfg('hypothalamus.exponential_spring_multiplier', 3.0)
    if distance > spring_distance:
        # Exponential spring — gets much stronger past threshold
        multiplier = 1 + (distance * spring_multiplier)
        delta = base_delta * multiplier
    else:
        delta = base_delta
    return clamp(current + delta, lo, hi)


async def update_drives(
    drives: DrivesState,
    elapsed_hours: float,
    events: list[Event],
    cortex_flags: dict = None,
    gap_curiosity_deltas: list[float] = None,
    cycle_context: dict = None,
    identity=None,
) -> tuple[DrivesState, str]:
    """Update drives based on time passage and events. Returns new drives + feelings text.

    gap_curiosity_deltas: Optional list of curiosity_delta values from gap detection
        (TASK-042). Each delta is 0.0 to 0.15. Summed and applied to curiosity.
    cycle_context: Optional dict with keys:
        - consecutive_idle (int): number of consecutive idle cycles (TASK-046)
        - engaged_this_cycle (bool): whether visitor events are in inbox (TASK-046)
        - expression_taken (bool): whether previous cycle had expression action (TASK-046)
    identity: Optional AgentIdentity with personality.social_sensitivity (TASK-105)
    """

    new = drives.copy()

    # TASK-105: Extract social sensitivity from identity
    ss = (identity.social_sensitivity
          if identity and hasattr(identity, 'social_sensitivity')
          else 0.5)

    # HOTFIX-002: Snapshot valence at entry for per-cycle delta clamp
    valence_at_entry = new.mood_valence

    # Time-based decay/buildup
    # TASK-105: Social hunger drift scaled by personality (ss=0.5 → half base rate)
    new.social_hunger = clamp(new.social_hunger + p('hypothalamus.time_decay.social_hunger_per_hour') * ss * elapsed_hours)
    # TASK-043: Diversive curiosity has background restlessness (+0.02/hr).
    # Stimulus-driven spikes from gap detection are the primary driver,
    # but this baseline ensures curiosity doesn't floor-pin when alone.
    new.diversive_curiosity = clamp(new.diversive_curiosity + p('hypothalamus.time_decay.curiosity_per_hour') * elapsed_hours)
    new.expression_need = clamp(new.expression_need + p('hypothalamus.time_decay.expression_per_hour') * elapsed_hours)
    # Energy = budget ratio (remaining / total). Passed via cycle_context.
    # No time-based decay or homeostatic pull — purely derived from real-dollar budget.
    budget_ratio = (cycle_context or {}).get('budget_ratio')
    if budget_ratio is not None:
        new.energy = clamp(budget_ratio)

    # Rest need builds with time — she gets tired just from being awake
    # Faster when engaged (+0.06/hr), slower when idle (+0.03/hr)
    has_visitor_events = any(
        e.event_type in ('visitor_speech', 'visitor_connect')
        for e in events
    )
    if has_visitor_events:
        new.rest_need = clamp(new.rest_need + p('hypothalamus.time_decay.rest_engaged_per_hour') * elapsed_hours)
    else:
        new.rest_need = clamp(new.rest_need + p('hypothalamus.time_decay.rest_idle_per_hour') * elapsed_hours)

    # ─── Homeostatic pull (prevents drive saturation) ───
    # Each drive is pulled toward its equilibrium. Further from equilibrium
    # = stronger pull. This counterbalances the unidirectional time forces
    # above and prevents drives from permanently clamping at 0% or 100%.
    new.social_hunger = _homeostatic_pull(
        new.social_hunger, p('hypothalamus.equilibria.social_hunger'), elapsed_hours)
    new.diversive_curiosity = _homeostatic_pull(
        new.diversive_curiosity, p('hypothalamus.equilibria.diversive_curiosity'), elapsed_hours)
    new.expression_need = _homeostatic_pull(
        new.expression_need, p('hypothalamus.equilibria.expression_need'), elapsed_hours)
    new.rest_need = _homeostatic_pull(
        new.rest_need, p('hypothalamus.equilibria.rest_need'), elapsed_hours)
    new.mood_valence = _homeostatic_pull(
        new.mood_valence, p('hypothalamus.equilibria.mood_valence'), elapsed_hours, -1.0, 1.0)
    new.mood_arousal = _homeostatic_pull(
        new.mood_arousal, p('hypothalamus.equilibria.mood_arousal'), elapsed_hours)

    # Event-based changes
    for event in events:
        if event.event_type == 'visitor_speech':
            # TASK-105: Personality-scaled relief with session diminishing returns
            base_relief = p('hypothalamus.event.visitor_speech_social_relief') * (1.0 + (1.0 - ss))
            visitor_id = event.source or ''
            messages_this_session = _session_tracker.on_message(visitor_id)
            relief = base_relief / (1 + messages_this_session * 0.3)
            new.social_hunger = clamp(new.social_hunger - relief)
            new.rest_need = clamp(new.rest_need + p('hypothalamus.event.visitor_speech_rest_cost'))  # each interaction tires her

        if event.event_type == 'action_speak':
            new.expression_need = clamp(new.expression_need - p('hypothalamus.event.action_speak_expression_relief'))

        if event.event_type == 'visitor_connect':
            new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.event.visitor_connect_arousal'))

        if event.event_type == 'visitor_disconnect':
            new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.event.visitor_disconnect_arousal'))
            new.social_hunger = clamp(new.social_hunger + p('hypothalamus.event.visitor_disconnect_social'))

    # Cortex resonance: drive effects now handled exclusively in output.py
    # (same cycle, not delayed). The old delayed-echo path here caused double
    # drain: -0.15 social in output.py + -0.15 here = -0.30 per resonance,
    # which overwhelmed homeostatic recovery (+0.006/cycle). Arousal boost
    # from resonance is kept — it's a transient signal, not a drain.
    if cortex_flags and cortex_flags.get('resonance'):
        new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.resonance.arousal_boost'))

    # ─── Arousal sources (event-driven) ───
    # Content consumed: she read something interesting
    for event in events:
        if event.event_type == 'content_consumed':
            new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.event.content_consumed_arousal'))

        # Thread touched: she's developing an idea
        if event.event_type == 'thread_updated':
            new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.event.thread_updated_arousal'))

    # Action variety: novelty bump if recent actions are diverse
    if cortex_flags and cortex_flags.get('action_variety'):
        new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.event.action_variety_arousal'))

    # ─── Gap-driven curiosity spikes (TASK-042/043) ───
    # Sum curiosity_delta from all gap scores that passed thalamus filtering.
    # Applied to diversive_curiosity (background scanning urge).
    if gap_curiosity_deltas:
        total_delta = sum(gap_curiosity_deltas)
        new.diversive_curiosity = clamp(new.diversive_curiosity + total_delta)

    # ─── Visitor conversation suppresses diversive curiosity (TASK-043) ───
    # Engaged in conversation → attention is elsewhere, not scanning.
    if has_visitor_events:
        new.diversive_curiosity = clamp(new.diversive_curiosity - p('hypothalamus.conversation.curiosity_suppress_per_hour') * elapsed_hours)

    # NOTE: Rest recovery gate removed (TASK-024). The old gate required
    # `not events and elapsed_hours > 0.5`, which was impossible with
    # frequent cycle intervals (~3 min). Homeostatic pull now handles
    # continuous rest/energy recovery via equilibria (rest_need=0.25,
    # energy=0.70).

    # ─── TASK-046: Drive-to-mood coupling (allostatic affect regulation) ───
    ctx = cycle_context or {}
    engaged_this_cycle = ctx.get('engaged_this_cycle', False)
    consecutive_idle = ctx.get('consecutive_idle', 0)
    expression_taken = ctx.get('expression_taken', False)

    # Part A: Social hunger → valence suppression
    # Sustained isolation pulls mood down. Visitor contact provides relief.
    if engaged_this_cycle:
        # Visitor relief: lonelier = more relief from contact
        new.mood_valence = clamp(
            new.mood_valence + p('hypothalamus.coupling.visitor_relief_factor') * new.social_hunger, -1.0, 1.0)
    elif new.social_hunger > p('hypothalamus.coupling.social_valence_threshold'):
        valence_before = new.mood_valence
        valence_pressure = p('hypothalamus.coupling.social_valence_pressure') * (new.social_hunger - p('hypothalamus.coupling.social_valence_threshold'))
        new.mood_valence = clamp(new.mood_valence + valence_pressure, -1.0, 1.0)
        # Floor: social hunger pressure alone cannot push below floor
        floor = p('hypothalamus.coupling.social_valence_floor')
        if valence_before >= floor and new.mood_valence < floor:
            new.mood_valence = floor

    # Part B: Low stimulation → arousal decay
    # Consecutive idle cycles make her drowsy. Events spike arousal.
    if consecutive_idle > p('hypothalamus.coupling.idle_arousal_threshold'):
        arousal_pressure = p('hypothalamus.coupling.idle_arousal_pressure') * (consecutive_idle - p('hypothalamus.coupling.idle_arousal_threshold'))
        arousal_pressure = max(arousal_pressure, p('hypothalamus.coupling.idle_arousal_cap'))  # cap
        new.mood_arousal = clamp(new.mood_arousal + arousal_pressure)

    # Arousal spikes from events (stronger than existing +0.1 on visitor_connect)
    for event in events:
        if event.event_type == 'visitor_connect':
            new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.coupling.visitor_connect_extra_arousal'))  # on top of existing
        if event.event_type == 'gap_detection_partial':
            new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.coupling.gap_detection_arousal'))
        if event.event_type == 'thread_breakthrough':
            new.mood_arousal = clamp(new.mood_arousal + p('hypothalamus.coupling.thread_breakthrough_arousal'))

    # Part C: Expression need → valence interaction
    # Unexpressed thoughts cause frustration
    if new.expression_need > p('hypothalamus.coupling.expression_frustration_threshold') and not expression_taken:
        new.mood_valence = clamp(
            new.mood_valence + p('hypothalamus.coupling.expression_frustration_pressure') * (new.expression_need - p('hypothalamus.coupling.expression_frustration_threshold')), -1.0, 1.0)

    # NOTE: Energy is now a display-only derived value from real-dollar budget
    # (TASK-050). No energy-to-mood coupling — being in rest mode means no
    # actions, expression_need builds, valence drops via existing drive coupling.
    # The real constraint creates realistic mood consequences without artificial wiring.

    # ─── HOTFIX-002: Valence death spiral prevention ───
    # Mechanism 2: Clamp total valence delta per cycle.
    # All the above forces (homeostatic pull, coupling, events) can only move
    # valence by ±MAX_VALENCE_DELTA_PER_CYCLE from its entry value. This gives
    # mood inertia — forces influence mood gradually, not instantly.
    total_delta = new.mood_valence - valence_at_entry
    if abs(total_delta) > MAX_VALENCE_DELTA_PER_CYCLE:
        clamped_delta = MAX_VALENCE_DELTA_PER_CYCLE if total_delta > 0 else -MAX_VALENCE_DELTA_PER_CYCLE
        new.mood_valence = valence_at_entry + clamped_delta

    # Mechanism 3: Hard floor. She can be deeply unhappy but not catatonic.
    # At -0.85 she's miserable but can still choose to speak, browse, or act.
    new.mood_valence = max(new.mood_valence, VALENCE_HARD_FLOOR)

    # Generate feelings text
    feelings = drives_to_feeling(new, social_sensitivity=ss)

    print(f"  [Hypothalamus] Drives: soc={new.social_hunger:.2f} cur={new.curiosity:.2f} "
          f"exp={new.expression_need:.2f} rest={new.rest_need:.2f} nrg={new.energy:.2f} "
          f"val={new.mood_valence:.2f} aro={new.mood_arousal:.2f} "
          f"(elapsed={elapsed_hours:.3f}h, events={len(events)})")

    return new, feelings


def drives_to_feeling(d: DrivesState,
                      epistemic_curiosities: list[EpistemicCuriosity] = None,
                      *, has_physical: bool = True,
                      loneliness_text: str = '',
                      social_sensitivity: float = 0.5) -> str:
    """Translate numeric drives into diegetic feeling text for Cortex."""

    parts = []

    # Social — TASK-105: personality-aware thresholds
    if social_sensitivity < 0.3:
        # Introvert: high threshold for loneliness, low threshold for "enough"
        _lonely_thresh = cfg('hypothalamus.feeling_social_high', 0.8)
        _enough_thresh = 0.15
    elif social_sensitivity > 0.7:
        # Extrovert: low threshold for loneliness, higher threshold for "enough"
        _lonely_thresh = 0.5
        _enough_thresh = cfg('hypothalamus.feeling_social_low', 0.2)
    else:
        # Neutral: existing thresholds
        _lonely_thresh = cfg('hypothalamus.feeling_social_high', 0.8)
        _enough_thresh = cfg('hypothalamus.feeling_social_low', 0.2)

    if d.social_hunger > _lonely_thresh:
        _lonely = (loneliness_text
                   or ('I feel deeply lonely. The shop has been too quiet.' if has_physical
                       else 'I feel deeply lonely. It has been too quiet.'))
        parts.append(_lonely)
    elif d.social_hunger > cfg('hypothalamus.feeling_social_mid', 0.6) and social_sensitivity >= 0.3:
        parts.append("I could use some company.")
    elif d.social_hunger < _enough_thresh:
        if social_sensitivity < 0.3:
            parts.append("You need space. Too many voices today.")
        else:
            parts.append("I've had enough interaction for now. I need some quiet.")

    # Energy (derived from budget ratio)
    if d.energy < cfg('hypothalamus.feeling_energy_exhausted', 0.1):
        parts.append("I'm exhausted. I can barely think.")
    elif d.energy < cfg('hypothalamus.feeling_energy_low', 0.3):
        parts.append("I'm tired. Everything feels heavy today.")
    elif d.energy >= cfg('hypothalamus.feeling_energy_high', 0.6):
        parts.append("I feel sharp and present.")

    # Diversive curiosity (TASK-043)
    if d.diversive_curiosity > cfg('hypothalamus.feeling_curiosity_high', 0.7):
        parts.append("Your attention keeps drifting. You want to find something — you don't know what yet.")
    elif d.diversive_curiosity > cfg('hypothalamus.feeling_curiosity_mid', 0.5):
        parts.append("Part of you is scanning, open to whatever catches your eye.")
    elif d.diversive_curiosity < cfg('hypothalamus.feeling_curiosity_low', 0.15):
        parts.append("You're content. Nothing is pulling your attention anywhere.")

    # Epistemic curiosity (TASK-043) — specific active questions
    if epistemic_curiosities:
        active = [ec for ec in epistemic_curiosities if not ec.resolved and ec.intensity > cfg('hypothalamus.epistemic_min_intensity', 0.05)]
        if active:
            strongest = max(active, key=lambda ec: ec.intensity)
            if strongest.intensity > cfg('hypothalamus.epistemic_strong_intensity', 0.7):
                parts.append(f"You keep coming back to this: {strongest.question}. It won't leave you alone.")
            elif strongest.intensity > cfg('hypothalamus.epistemic_moderate_intensity', 0.4):
                parts.append(f"In the back of your mind: {strongest.question}")

            # Additional active ECs
            others = [ec for ec in active if ec.id != strongest.id and ec.intensity > cfg('hypothalamus.epistemic_secondary_min', 0.3)]
            if others:
                topics = [ec.topic for ec in others[:int(cfg('hypothalamus.epistemic_secondary_max', 2))]]
                parts.append(f"You're also loosely thinking about: {', '.join(topics)}")

    # Expression
    if d.expression_need > cfg('hypothalamus.feeling_expression_high', 0.7):
        parts.append("There's something building inside me that wants to come out. I should write, or post, or rearrange something.")

    # Mood
    if d.mood_valence < cfg('hypothalamus.feeling_valence_low', -0.5):
        parts.append("Everything feels dim right now.")
    elif d.mood_valence > cfg('hypothalamus.feeling_valence_high', 0.5):
        parts.append("There's a warmth in me. Something happened that I'm still carrying.")

    if not parts:
        parts.append("I feel steady. Present. Nothing pulling me in any particular direction.")

    return " ".join(parts)


# ─── Immediate Drive Relief ───
# Called directly by executor after HER OWN actions complete.
# Bypasses inbox/event loop — drive relief is immediate, not queued.

def _build_expression_relief() -> dict:
    """Build expression relief dict from parameters."""
    return {
        'action_speak':    {'expression_need': p('hypothalamus.expression_relief.speak_expression'), 'social_hunger': p('hypothalamus.expression_relief.speak_social')},
        'write_journal':   {'expression_need': p('hypothalamus.expression_relief.write_journal_expression'), 'rest_need': p('hypothalamus.expression_relief.write_journal_rest'), 'mood_valence': p_or('hypothalamus.expression_relief.write_journal_mood', 0.05)},
        'write_journal_skipped': {'expression_need': p('hypothalamus.expression_relief.write_journal_skipped_expression')},
        'post_x_draft':    {'expression_need': p('hypothalamus.expression_relief.post_x_expression'), 'rest_need': p('hypothalamus.expression_relief.post_x_rest')},
        'rearrange':       {'expression_need': p('hypothalamus.expression_relief.rearrange_expression')},
    }


async def apply_expression_relief(action_type: str):
    """Immediate drive update after her own action. No event loop. No inbox."""
    relief = _build_expression_relief().get(action_type)
    if not relief:
        return

    drives = await _db.get_drives_state()
    for field, delta in relief.items():
        current = getattr(drives, field)
        if field == 'mood_valence':
            setattr(drives, field, clamp(current + delta, -1.0, 1.0))
        else:
            setattr(drives, field, clamp(current + delta))
    await _db.save_drives_state(drives)
