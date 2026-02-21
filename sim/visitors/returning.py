"""sim.visitors.returning — Tier 3 returning visitor scheduling.

Handles return visit scheduling, memory stub generation, and visit
tracking for visitors that come back to the shop after their initial
visit. Any tier visitor can be flagged for return; on return they
become Tier 3 with populated visit_history and memory_stub.

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

        return_arrivals.sort(key=lambda a: a.cycle)
        return return_arrivals

    def get_return_entering_text(
        self, visitor: VisitorInstance, rng: random.Random,
    ) -> str:
        """Get entering dialogue for a returning visitor.

        Fills template slots with context from the visitor's previous
        visit history.

        Args:
            visitor: The returning visitor instance (Tier 3).
            rng: Seeded RNG for template selection.

        Returns:
            Dialogue text referencing the past visit.
        """
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

    @property
    def flagged_count(self) -> int:
        """Number of visitors flagged for return."""
        return len(self._flagged)

    @property
    def memory_stubs(self) -> dict[str, str]:
        """Memory stubs for all flagged visitors."""
        return dict(self._memory_stubs)
