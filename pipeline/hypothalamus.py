"""Hypothalamus — drives math. Deterministic. No LLM."""

from models.event import Event
from models.state import DrivesState, EpistemicCuriosity, EPISTEMIC_CONFIG
from db.parameters import p
import db as _db


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _homeostatic_pull(current: float, equilibrium: float,
                      elapsed_hours: float,
                      lo: float = 0.0, hi: float = 1.0) -> float:
    """Pull a drive toward its equilibrium point.

    Proportional spring: further from equilibrium = stronger pull.
    At extremes (distance ~0.5-1.0), pull is ~0.075-0.15/hr,
    which competes meaningfully with time-based forces (+0.03-0.06/hr).
    Near equilibrium, pull vanishes, letting natural variation emerge.
    """
    delta = (equilibrium - current) * p('hypothalamus.homeostatic_pull_rate') * elapsed_hours
    return clamp(current + delta, lo, hi)


async def update_drives(
    drives: DrivesState,
    elapsed_hours: float,
    events: list[Event],
    cortex_flags: dict = None,
    gap_curiosity_deltas: list[float] = None,
    cycle_context: dict = None,
) -> tuple[DrivesState, str]:
    """Update drives based on time passage and events. Returns new drives + feelings text.

    gap_curiosity_deltas: Optional list of curiosity_delta values from gap detection
        (TASK-042). Each delta is 0.0 to 0.15. Summed and applied to curiosity.
    cycle_context: Optional dict with keys:
        - consecutive_idle (int): number of consecutive idle cycles (TASK-046)
        - engaged_this_cycle (bool): whether visitor events are in inbox (TASK-046)
        - expression_taken (bool): whether previous cycle had expression action (TASK-046)
    """

    new = drives.copy()

    # Time-based decay/buildup
    new.social_hunger = clamp(new.social_hunger + p('hypothalamus.time_decay.social_hunger_per_hour') * elapsed_hours)
    # TASK-043: Diversive curiosity has background restlessness (+0.02/hr).
    # Stimulus-driven spikes from gap detection are the primary driver,
    # but this baseline ensures curiosity doesn't floor-pin when alone.
    new.diversive_curiosity = clamp(new.diversive_curiosity + p('hypothalamus.time_decay.curiosity_per_hour') * elapsed_hours)
    new.expression_need = clamp(new.expression_need + p('hypothalamus.time_decay.expression_per_hour') * elapsed_hours)
    # NOTE: energy field is now a display-only derived value from real-dollar
    # budget (TASK-050). No time-based decay or homeostatic pull on energy.

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
            new.social_hunger = clamp(new.social_hunger - p('hypothalamus.event.visitor_speech_social_relief'))
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

    # Generate feelings text
    feelings = drives_to_feeling(new)

    print(f"  [Hypothalamus] Drives: soc={new.social_hunger:.2f} cur={new.curiosity:.2f} "
          f"exp={new.expression_need:.2f} rest={new.rest_need:.2f} nrg={new.energy:.2f} "
          f"val={new.mood_valence:.2f} aro={new.mood_arousal:.2f} "
          f"(elapsed={elapsed_hours:.3f}h, events={len(events)})")

    return new, feelings


def drives_to_feeling(d: DrivesState,
                      epistemic_curiosities: list[EpistemicCuriosity] = None) -> str:
    """Translate numeric drives into diegetic feeling text for Cortex."""

    parts = []

    # Social
    if d.social_hunger > 0.8:
        parts.append("I feel deeply lonely. The shop has been too quiet.")
    elif d.social_hunger > 0.6:
        parts.append("I could use some company.")
    elif d.social_hunger < 0.2:
        parts.append("I've had enough interaction for now. I need some quiet.")

    # Energy
    if d.energy < 0.3:
        parts.append("I'm tired. Everything feels heavy today.")
    elif d.energy > 0.8:
        parts.append("I feel sharp and present.")

    # Diversive curiosity (TASK-043)
    if d.diversive_curiosity > 0.7:
        parts.append("Your attention keeps drifting. You want to find something — you don't know what yet.")
    elif d.diversive_curiosity > 0.5:
        parts.append("Part of you is scanning, open to whatever catches your eye.")
    elif d.diversive_curiosity < 0.15:
        parts.append("You're content. Nothing is pulling your attention anywhere.")

    # Epistemic curiosity (TASK-043) — specific active questions
    if epistemic_curiosities:
        active = [ec for ec in epistemic_curiosities if not ec.resolved and ec.intensity > 0.05]
        if active:
            strongest = max(active, key=lambda ec: ec.intensity)
            if strongest.intensity > 0.7:
                parts.append(f"You keep coming back to this: {strongest.question}. It won't leave you alone.")
            elif strongest.intensity > 0.4:
                parts.append(f"In the back of your mind: {strongest.question}")

            # Additional active ECs
            others = [ec for ec in active if ec.id != strongest.id and ec.intensity > 0.3]
            if others:
                topics = [ec.topic for ec in others[:2]]
                parts.append(f"You're also loosely thinking about: {', '.join(topics)}")

    # Expression
    if d.expression_need > 0.7:
        parts.append("There's something building inside me that wants to come out. I should write, or post, or rearrange something.")

    # Mood
    if d.mood_valence < -0.5:
        parts.append("Everything feels dim right now.")
    elif d.mood_valence > 0.5:
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
        'write_journal':   {'expression_need': p('hypothalamus.expression_relief.write_journal_expression'), 'rest_need': p('hypothalamus.expression_relief.write_journal_rest')},
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
        setattr(drives, field, clamp(current + delta))
    await _db.save_drives_state(drives)
