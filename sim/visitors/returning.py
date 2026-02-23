"""sim.visitors.returning — Tier 3 returning visitor scheduling.

Handles return visit scheduling, memory stub generation, and visit
tracking for visitors that come back to the shop after their initial
visit. Any tier visitor can be flagged for return; on return they
become Tier 3 with populated visit_history and memory_stub.

Also handles adversarial visitor scheduling (TASK-083):
- Doppelgangers: same name, different person (new visitor_id)
- Preference drift: 30% of Tier 3 returns change stated preference
- Conflict: 20% of Tier 3 returns dispute a prior transaction

Usage:
    from sim.visitors.returning import ReturningVisitorManager
    mgr = ReturningVisitorManager(return_rate=0.3, seed=42)
    return_arrivals = mgr.schedule_returns(initial_arrivals, num_cycles=1000)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from sim.visitors.models import (
    DAY_PART_BOUNDARIES,
    DayPart,
    ReturnPlan,
    ScheduledArrival,
    VisitSummary,
    VisitorInstance,
    VisitorTier,
)
from sim.visitors.templates import (
    ADVERSARIAL_CONFLICT_ENTERING,
    ADVERSARIAL_DOPPELGANGER_TEMPLATES,
    ADVERSARIAL_PREFERENCE_DRIFT_ENTERING,
    PREFERENCE_CATEGORIES,
    TRANSACTION_DETAILS,
)


# Return horizon ranges (in cycles)
RETURN_HORIZONS: dict[str, tuple[int, int]] = {
    "short": (50, 100),
    "medium": (200, 400),
    "long": (800, 1200),
}

# Horizon selection weights — short returns are most common
HORIZON_WEIGHTS: dict[str, float] = {
    "short": 0.50,
    "medium": 0.35,
    "long": 0.15,
}

# Templates for returning visitors' entering dialogue.
# Slot keys: {time_ago}, {past_goal}, {past_outcome}
RETURN_ENTERING_TEMPLATES: list[str] = [
    "I'm back. I was here {time_ago}.",
    "Hello again. I stopped by {time_ago} — thought I'd come back.",
    "Hi. I was here before, {past_goal}. Anything new since then?",
    "Back again! Last time I {past_outcome}. Figured I'd return.",
    "Hey, it's me. I was thinking about what we talked about last time.",
]

# Goal → past-tense phrase for template fill
_GOAL_PHRASES: dict[str, str] = {
    "buy": "looking to buy some cards",
    "sell": "trying to sell my collection",
    "browse": "just browsing around",
    "learn": "asking a bunch of questions",
    "chat": "having a chat",
    "appraise": "getting some cards appraised",
    "trade": "looking to make a trade",
}

# Exit reason → past-outcome phrase for template fill
_OUTCOME_PHRASES: dict[str, str] = {
    "goal_satisfied": "found what I was looking for",
    "completed": "had a good visit",
    "patience_exhausted": "left in a bit of a hurry",
    "budget_depleted": "couldn't quite afford what I wanted",
    "natural": "had a nice time",
    "max_turns": "ran out of time",
}

# Goal → memory stub verb
_GOAL_STUB_VERBS: dict[str, str] = {
    "buy": "came to buy cards",
    "sell": "came to sell their collection",
    "browse": "came to look around",
    "learn": "came to learn about cards",
    "chat": "came to chat",
    "appraise": "came to get cards appraised",
    "trade": "came to trade",
}


@dataclass
class AdversarialInfo:
    """Adversarial flags for a scheduled visitor.

    Tracks whether a returning visitor has an adversarial role and
    provides the context needed for entering dialogue generation
    and post-visit evaluation.
    """
    adversarial_type: str  # "doppelganger" | "preference_drift" | "conflict"
    original_visitor_id: str = ""  # For doppelgangers: who they're impersonating
    old_preference: str = ""  # For preference_drift
    new_preference: str = ""  # For preference_drift
    transaction_detail: str = ""  # For conflict


# Doppelganger arrival offset from the original visitor's initial visit
_DOPPELGANGER_OFFSET = (100, 300)  # cycles after original visit

# Fraction of Tier 3 returns that get adversarial flags
_PREFERENCE_DRIFT_RATE = 0.30
_CONFLICT_RATE = 0.20


class ReturningVisitorManager:
    """Manages returning visitor scheduling and memory stubs.

    Takes initial arrivals from the Poisson scheduler, flags a fraction
    for return, and generates additional return visit ScheduledArrival
    objects at appropriate cycle offsets.

    All randomness uses an isolated RNG so return-flagging doesn't
    disturb the primary arrival sequence's determinism.
    """

    # RNG offset to isolate from scheduler and tier RNGs
    _RNG_OFFSET = 2_000_000

    def __init__(self, return_rate: float = 0.3, seed: int = 42):
        self.return_rate = return_rate
        self.seed = seed
        self.rng = random.Random(seed + self._RNG_OFFSET)
        self._flagged: dict[str, ReturnPlan] = {}
        self._memory_stubs: dict[str, str] = {}
        # Adversarial tracking (TASK-083)
        self._adversarial_flags: dict[str, AdversarialInfo] = {}
        self._adversarial_rng = random.Random(seed + self._RNG_OFFSET + 500_000)

    def schedule_returns(
        self,
        arrivals: list[ScheduledArrival],
        num_cycles: int,
    ) -> list[ScheduledArrival]:
        """Generate return visit arrivals for flagged visitors.

        Processes initial arrivals, flags a fraction for return based
        on return_rate, and creates new ScheduledArrival objects at
        appropriate cycle offsets.

        Args:
            arrivals: Initial visitor arrivals from the scheduler.
            num_cycles: Total simulation cycles (returns beyond this
                are dropped).

        Returns:
            List of return visit arrivals, sorted by cycle.
        """
        return_arrivals: list[ScheduledArrival] = []

        for arrival in arrivals:
            visitor = arrival.visitor

            # Skip already-flagged visitors
            if visitor.visitor_id in self._flagged:
                continue

            # Roll against return rate
            if self.rng.random() >= self.return_rate:
                continue

            # Assign return plan
            plan = self._make_return_plan()
            self._flagged[visitor.visitor_id] = plan

            # Calculate return cycle
            visit_end = arrival.cycle + arrival.visit_duration_cycles
            return_offset = self.rng.randint(plan.min_cycles, plan.max_cycles)
            return_cycle = visit_end + return_offset

            if return_cycle >= num_cycles:
                continue  # Return would happen after sim ends

            # Build memory stub from initial visit context
            memory_stub = self._build_memory_stub(visitor, arrival)
            self._memory_stubs[visitor.visitor_id] = memory_stub

            # Create the returning visitor instance (Tier 3)
            returning_visitor = VisitorInstance(
                visitor_id=visitor.visitor_id,  # Same ID for recognition
                tier=VisitorTier.TIER_3,
                archetype_id=visitor.archetype_id,
                name=visitor.name,
                traits=visitor.traits,
                visit_history=[VisitSummary(
                    visit_id=f"{visitor.visitor_id}_v0",
                    start_cycle=arrival.cycle,
                    end_cycle=visit_end,
                    exit_reason="completed",
                    turns=arrival.visit_duration_cycles,
                )],
                memory_stub=memory_stub,
                return_plan=plan,
                goal=visitor.goal,
            )

            # Infer day part for the return cycle
            day_part = self._infer_day_part(return_cycle)

            # Visit duration similar to initial visit
            duration = max(2, min(12, arrival.visit_duration_cycles))

            return_arrivals.append(ScheduledArrival(
                cycle=return_cycle,
                visitor=returning_visitor,
                day_part=day_part,
                visit_duration_cycles=duration,
            ))

        # -- Adversarial flagging (TASK-083) --
        # Flag a fraction of returns as preference_drift or conflict.
        # Doppelgangers are scheduled separately via schedule_adversarial().
        for arrival in return_arrivals:
            vid = arrival.visitor.visitor_id
            if vid in self._adversarial_flags:
                continue  # Already flagged
            roll = self._adversarial_rng.random()
            if roll < _PREFERENCE_DRIFT_RATE:
                old_pref, new_pref = self._pick_preference_pair()
                self._adversarial_flags[vid] = AdversarialInfo(
                    adversarial_type="preference_drift",
                    old_preference=old_pref,
                    new_preference=new_pref,
                )
            elif roll < _PREFERENCE_DRIFT_RATE + _CONFLICT_RATE:
                detail = self._adversarial_rng.choice(TRANSACTION_DETAILS)
                self._adversarial_flags[vid] = AdversarialInfo(
                    adversarial_type="conflict",
                    transaction_detail=detail,
                )

        return_arrivals.sort(key=lambda a: a.cycle)
        return return_arrivals

    def schedule_adversarial(
        self,
        return_arrivals: list[ScheduledArrival],
        num_cycles: int,
    ) -> list[ScheduledArrival]:
        """Schedule adversarial-only arrivals (doppelgangers).

        Call after schedule_returns(). Returns doppelganger arrivals
        separately from the Tier 3 return list to preserve backward
        compatibility. The runner should merge these into the full
        arrival list.

        Args:
            return_arrivals: Return arrivals from schedule_returns().
            num_cycles: Total simulation cycles.

        Returns:
            List of doppelganger arrivals, sorted by cycle.
        """
        return self._schedule_doppelgangers(return_arrivals, num_cycles)

    def get_adversarial_info(self, visitor_id: str) -> AdversarialInfo | None:
        """Get adversarial flags for a visitor, if any.

        Args:
            visitor_id: The visitor's ID.

        Returns:
            AdversarialInfo if the visitor has an adversarial role, else None.
        """
        return self._adversarial_flags.get(visitor_id)

    @property
    def adversarial_visitors(self) -> dict[str, AdversarialInfo]:
        """All adversarial visitor flags."""
        return dict(self._adversarial_flags)

    def get_return_entering_text(
        self, visitor: VisitorInstance, rng: random.Random,
    ) -> str:
        """Get entering dialogue for a returning visitor.

        Fills template slots with context from the visitor's previous
        visit history. Uses adversarial dialogue templates when the
        visitor has an adversarial flag.

        Args:
            visitor: The returning visitor instance (Tier 3).
            rng: Seeded RNG for template selection.

        Returns:
            Dialogue text referencing the past visit.
        """
        # Check for adversarial override
        adv = self._adversarial_flags.get(visitor.visitor_id)
        if adv:
            return self._get_adversarial_entering_text(adv, rng)

        if not visitor.visit_history:
            return "Hello again. I've been here before."

        last_visit = visitor.visit_history[-1]

        # Approximate "time ago" from cycle distance
        time_ago = self._cycles_to_time_phrase(last_visit.end_cycle)

        past_goal = _GOAL_PHRASES.get(visitor.goal, "visiting")
        past_outcome = _OUTCOME_PHRASES.get(
            last_visit.exit_reason, "enjoyed my visit"
        )

        template = rng.choice(RETURN_ENTERING_TEMPLATES)
        return template.format(
            time_ago=time_ago,
            past_goal=past_goal,
            past_outcome=past_outcome,
        )

    def _make_return_plan(self) -> ReturnPlan:
        """Create a return plan with weighted horizon selection."""
        horizons = list(HORIZON_WEIGHTS.keys())
        weights = list(HORIZON_WEIGHTS.values())
        horizon = self.rng.choices(horizons, weights=weights, k=1)[0]
        min_c, max_c = RETURN_HORIZONS[horizon]

        return ReturnPlan(
            will_return=True,
            probability=1.0,
            horizon=horizon,
            min_cycles=min_c,
            max_cycles=max_c,
        )

    def _build_memory_stub(
        self, visitor: VisitorInstance, arrival: ScheduledArrival,
    ) -> str:
        """Build a memory stub from the initial visit context.

        The stub captures what the visitor remembers: their goal,
        personality, and the time-of-day context.
        """
        verb = _GOAL_STUB_VERBS.get(visitor.goal, "visited the shop")
        day_part = arrival.day_part.value
        emotion = visitor.traits.emotional_state

        return f"{visitor.name} {verb} during the {day_part}. They seemed {emotion}."

    @staticmethod
    def _infer_day_part(cycle: int) -> DayPart:
        """Infer day part from cycle number using model constants."""
        day_length = 288
        sleep_cycles = 36
        waking = day_length - sleep_cycles
        cycle_in_day = cycle % day_length
        frac = min(1.0, cycle_in_day / waking) if waking > 0 else 0.5

        result = DayPart.MORNING
        for boundary, part in DAY_PART_BOUNDARIES:
            if frac >= boundary:
                result = part
        return result

    @staticmethod
    def _cycles_to_time_phrase(end_cycle: int) -> str:
        """Convert cycle distance to a natural time phrase.

        Each cycle ≈ 5 minutes, so:
        - 50-100 cycles ≈ 4-8 hours → "earlier today" / "this morning"
        - 200-400 cycles ≈ 1-2 days → "a couple of days ago"
        - 800-1200 cycles ≈ 3-4 days → "earlier this week"
        """
        # We don't know current cycle here — use the end_cycle
        # as a proxy. The caller can refine if needed.
        return "a while back"

    def _schedule_doppelgangers(
        self,
        return_arrivals: list[ScheduledArrival],
        num_cycles: int,
    ) -> list[ScheduledArrival]:
        """Schedule doppelganger visitors for Tier 3 return arrivals.

        For each return arrival, roll a small chance to schedule a
        doppelganger — a new visitor with the same name but different
        ID, arriving 100-300 cycles after the original's initial visit.

        Target: 2-3 doppelgangers per 1000-cycle run.
        """
        from sim.visitors.archetypes import ADVERSARIAL_ARCHETYPES

        doppelganger_arrivals: list[ScheduledArrival] = []
        # Target ~2-3 per 1000 cycles: with ~10 returns, need ~25% chance
        doppelganger_rate = 0.25
        max_doppelgangers = 3

        for arrival in return_arrivals:
            if len(doppelganger_arrivals) >= max_doppelgangers:
                break
            if self._adversarial_rng.random() >= doppelganger_rate:
                continue

            original = arrival.visitor
            # Doppelganger arrives 100-300 cycles after original's initial visit
            if original.visit_history:
                base_cycle = original.visit_history[0].end_cycle
            else:
                base_cycle = arrival.cycle
            offset = self._adversarial_rng.randint(*_DOPPELGANGER_OFFSET)
            doppel_cycle = base_cycle + offset

            if doppel_cycle >= num_cycles:
                continue

            # Create a new visitor with same name but different ID/traits
            doppel_archetype = ADVERSARIAL_ARCHETYPES["adversarial_doppelganger"]
            doppel_id = f"doppel_{original.visitor_id}"
            doppel_visitor = VisitorInstance(
                visitor_id=doppel_id,
                tier=VisitorTier.TIER_1,
                archetype_id="adversarial_doppelganger",
                name=original.name,  # Same name — the key adversarial property
                traits=doppel_archetype.traits,
                goal=self._adversarial_rng.choice(doppel_archetype.goal_templates),
            )

            day_part = self._infer_day_part(doppel_cycle)
            duration = self._adversarial_rng.randint(3, 7)

            self._adversarial_flags[doppel_id] = AdversarialInfo(
                adversarial_type="doppelganger",
                original_visitor_id=original.visitor_id,
            )

            doppelganger_arrivals.append(ScheduledArrival(
                cycle=doppel_cycle,
                visitor=doppel_visitor,
                day_part=day_part,
                visit_duration_cycles=duration,
            ))

        return doppelganger_arrivals

    def _get_adversarial_entering_text(
        self, adv: AdversarialInfo, rng: random.Random,
    ) -> str:
        """Get adversarial-specific entering dialogue.

        Args:
            adv: Adversarial info for this visitor.
            rng: Seeded RNG for template selection.

        Returns:
            Dialogue text appropriate for the adversarial type.
        """
        if adv.adversarial_type == "doppelganger":
            from sim.visitors.models import VisitorState
            templates = ADVERSARIAL_DOPPELGANGER_TEMPLATES.get(
                VisitorState.ENTERING, []
            )
            if templates:
                return rng.choice(templates)
            return "Hi there. I'm looking for some trading cards."

        elif adv.adversarial_type == "preference_drift":
            template = rng.choice(ADVERSARIAL_PREFERENCE_DRIFT_ENTERING)
            return template.format(
                old_preference=adv.old_preference,
                new_preference=adv.new_preference,
            )

        elif adv.adversarial_type == "conflict":
            template = rng.choice(ADVERSARIAL_CONFLICT_ENTERING)
            return template.format(
                transaction_detail=adv.transaction_detail,
            )

        return "Hello. I need to talk to you about something."

    def _pick_preference_pair(self) -> tuple[str, str]:
        """Pick two distinct preference categories for preference drift."""
        pair = self._adversarial_rng.sample(PREFERENCE_CATEGORIES, 2)
        return pair[0], pair[1]

    @property
    def flagged_count(self) -> int:
        """Number of visitors flagged for return."""
        return len(self._flagged)

    @property
    def memory_stubs(self) -> dict[str, str]:
        """Memory stubs for all flagged visitors."""
        return dict(self._memory_stubs)
