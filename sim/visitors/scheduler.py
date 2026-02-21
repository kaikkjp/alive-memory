"""sim.visitors.scheduler — Poisson arrival process with day-part modulation.

Generates deterministic visitor arrival schedules based on:
- Base arrival rate (lambda) per scenario
- Day-part multipliers (morning/lunch/afternoon/evening)
- Weekday/weekend multipliers
- Scenario-specific modulation

All randomness uses seeded RNG for reproducibility.

Usage:
    from sim.visitors.scheduler import VisitorScheduler
    scheduler = VisitorScheduler(scenario="standard", seed=42)
    arrivals = scheduler.generate(num_cycles=1000, day_length=288)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from sim.visitors.models import (
    DayPart,
    DAY_PART_BOUNDARIES,
    DAY_PART_MULTIPLIERS,
    ScheduledArrival,
    VisitorInstance,
    VisitorTier,
    VisitorTraits,
)
from sim.visitors.archetypes import pick_archetype, pick_goal


@dataclass
class ScenarioConfig:
    """Configuration for a simulation scenario's visitor generation."""
    name: str
    base_rate: float            # Lambda for Poisson process
    tier1_enabled: bool = True  # Tier 1 scripted visitors
    tier2_enabled: bool = False  # Tier 2 LLM visitors (PR #4)
    tier3_enabled: bool = False  # Tier 3 returning visitors (PR #3)
    tier2_fraction: float = 0.0  # Fraction of visits using LLM
    tier3_return_rate: float = 0.0  # Fraction of Tier 2 flagged for return
    weekend_multiplier: float = 1.5
    weekday_multiplier: float = 1.0


# Scenario presets from spec
SCENARIO_CONFIGS: dict[str, ScenarioConfig] = {
    "isolation": ScenarioConfig(
        name="isolation",
        base_rate=0.0,
    ),
    "standard": ScenarioConfig(
        name="standard",
        base_rate=0.15,
        tier1_enabled=True,
    ),
    "social": ScenarioConfig(
        name="social",
        base_rate=0.15,
        tier1_enabled=True,
        tier2_enabled=True,
        tier2_fraction=0.5,
    ),
    "stress": ScenarioConfig(
        name="stress",
        base_rate=0.40,
        tier1_enabled=True,
        tier2_enabled=True,
        tier2_fraction=0.8,
    ),
    "returning": ScenarioConfig(
        name="returning",
        base_rate=0.15,
        tier1_enabled=True,
        tier2_enabled=True,
        tier3_enabled=True,
        tier2_fraction=0.5,
        tier3_return_rate=0.3,
    ),
}


class VisitorScheduler:
    """Generates deterministic visitor arrival schedules.

    Uses a Poisson process modulated by day-part, weekday/weekend,
    and scenario multipliers. Produces a list of ScheduledArrival
    objects that the runner injects as events.
    """

    # Full day: 24 hours = 288 cycles of 5min each
    # Sleep window: 3AM-6AM JST = 36 cycles
    # The runner advances clock BEFORE processing each cycle, so
    # cycle_in_day N sees clock time = start + (N+1)*5min.
    # 3:00 AM = 18h after 9AM = 1080min → (N+1)*5=1080 → N=215
    # 6:00 AM = 21h after 9AM = 1260min → (N+1)*5=1260 → N=251
    # Sleep cycles: 215..250 inclusive, i.e. [215, 251) = 36 cycles
    CYCLES_PER_DAY = 288
    SLEEP_CYCLES = 36   # 3 hours
    WAKING_CYCLES = 252  # 21 hours
    SLEEP_START = 215   # first cycle where runner clock hits 3:00 AM
    SLEEP_END = 251     # first cycle where runner clock hits 6:00 AM (not sleep)

    # Shop is open roughly 10AM-10PM (12 hours = 144 cycles)
    # We use the full waking period for potential arrivals though,
    # with day-part modulation handling the distribution.

    def __init__(
        self,
        scenario: str = "standard",
        seed: int = 42,
        config: ScenarioConfig | None = None,
    ):
        if config:
            self.config = config
        elif scenario in SCENARIO_CONFIGS:
            self.config = SCENARIO_CONFIGS[scenario]
        else:
            raise ValueError(
                f"Unknown scenario: {scenario}. "
                f"Available: {list(SCENARIO_CONFIGS.keys())}"
            )
        self.seed = seed
        self.rng = random.Random(seed)

    def generate(
        self,
        num_cycles: int = 1000,
        day_length: int | None = None,
    ) -> list[ScheduledArrival]:
        """Generate visitor arrivals for the full simulation.

        Args:
            num_cycles: Total cycles to schedule.
            day_length: Cycles per day (default: CYCLES_PER_DAY).

        Returns:
            Sorted list of ScheduledArrival objects.
        """
        if day_length is None:
            day_length = self.CYCLES_PER_DAY

        if self.config.base_rate <= 0:
            return []

        arrivals: list[ScheduledArrival] = []
        visitor_counter = 0

        for cycle in range(num_cycles):
            # Check if this cycle is in sleep window
            if self._is_sleep_cycle(cycle, day_length):
                continue

            # Calculate arrival probability for this cycle
            p = self._arrival_probability(cycle, day_length)

            # Roll for arrival using per-cycle deterministic seed
            cycle_rng = random.Random(self.seed + cycle)
            if cycle_rng.random() < p:
                # Generate a visitor
                day_part = self._get_day_part(cycle, day_length)
                visitor = self._generate_visitor(visitor_counter)
                duration = self._generate_visit_duration(visitor)

                arrivals.append(ScheduledArrival(
                    cycle=cycle,
                    visitor=visitor,
                    day_part=day_part,
                    visit_duration_cycles=duration,
                ))
                visitor_counter += 1

        return arrivals

    def _arrival_probability(
        self, cycle: int, day_length: int
    ) -> float:
        """Calculate p_arrival for a specific cycle.

        p_arrival(cycle) = 1 - exp(-lambda(t))
        where lambda(t) = base_rate * day_part_mult * weekday_mult
        """
        day_part = self._get_day_part(cycle, day_length)
        day_part_mult = DAY_PART_MULTIPLIERS[day_part]

        day_of_week = (cycle // day_length) % 7
        is_weekend = day_of_week >= 5
        weekday_mult = (
            self.config.weekend_multiplier if is_weekend
            else self.config.weekday_multiplier
        )

        lambda_t = self.config.base_rate * day_part_mult * weekday_mult

        return 1.0 - math.exp(-lambda_t)

    def _is_sleep_cycle(self, cycle: int, day_length: int) -> bool:
        """Check if a cycle falls in the sleep window (3AM-6AM JST).

        The runner advances the clock BEFORE processing, so cycle N
        sees clock time start + (N+1)*5min. SLEEP_START/END account
        for this offset to match SimulatedClock.is_sleep_window.
        """
        cycle_in_day = cycle % day_length
        return self.SLEEP_START <= cycle_in_day < self.SLEEP_END

    def _get_day_part(self, cycle: int, day_length: int) -> DayPart:
        """Determine the day-part for a given cycle.

        Uses fractional position within the waking period.
        """
        cycle_in_day = cycle % day_length
        waking_cycles = day_length - self.SLEEP_CYCLES
        if waking_cycles <= 0:
            return DayPart.AFTERNOON

        # Fraction of waking day elapsed
        frac = cycle_in_day / waking_cycles
        frac = min(frac, 1.0)

        # Find the matching day part
        result = DayPart.MORNING
        for boundary, part in DAY_PART_BOUNDARIES:
            if frac >= boundary:
                result = part
        return result

    def _generate_visitor(self, counter: int) -> VisitorInstance:
        """Generate a visitor from archetype selection.

        Picks a weighted-random archetype, assigns its traits and a
        goal from the archetype's goal_templates.  Tier assignment uses
        a separate RNG keyed by counter so enabling Tier 2 doesn't
        disturb the Tier 1 trait/archetype sequence.
        """
        visitor_id = f"sim:visitor_{counter:04d}"

        archetype = pick_archetype(self.rng)
        goal = pick_goal(archetype, self.rng)

        # Determine tier with an isolated RNG (preserves Tier 1 determinism)
        tier = VisitorTier.TIER_1
        if self.config.tier2_enabled:
            tier_rng = random.Random(self.seed + 1_000_000 + counter)
            if tier_rng.random() < self.config.tier2_fraction:
                tier = VisitorTier.TIER_2

        return VisitorInstance(
            visitor_id=visitor_id,
            tier=tier,
            archetype_id=archetype.archetype_id,
            name=archetype.name,
            traits=archetype.traits,
            goal=goal,
        )

    def _generate_visit_duration(self, visitor: VisitorInstance) -> int:
        """Generate expected visit duration in cycles.

        Based on patience trait: higher patience = longer visits.
        Range: 2-12 cycles (10-60 minutes in sim time).
        """
        min_dur = 2
        max_dur = 12
        patience = visitor.traits.patience

        # Base duration scaled by patience
        base = min_dur + (max_dur - min_dur) * patience
        # Add some jitter
        jitter = self.rng.uniform(-1.5, 1.5)
        duration = int(round(base + jitter))
        return max(min_dur, min(max_dur, duration))

    def arrivals_in_range(
        self,
        arrivals: list[ScheduledArrival],
        start_cycle: int,
        end_cycle: int,
    ) -> list[ScheduledArrival]:
        """Filter arrivals to a specific cycle range."""
        return [a for a in arrivals if start_cycle <= a.cycle < end_cycle]

    def stats(
        self, arrivals: list[ScheduledArrival], num_cycles: int
    ) -> dict:
        """Compute summary statistics for a generated schedule."""
        if not arrivals:
            return {
                "total_visitors": 0,
                "visitors_per_day": 0.0,
                "by_day_part": {},
                "mean_duration": 0.0,
            }

        day_part_counts: dict[str, int] = {}
        durations: list[int] = []

        for a in arrivals:
            dp = a.day_part.value
            day_part_counts[dp] = day_part_counts.get(dp, 0) + 1
            durations.append(a.visit_duration_cycles)

        num_days = max(1, num_cycles / self.CYCLES_PER_DAY)

        return {
            "total_visitors": len(arrivals),
            "visitors_per_day": len(arrivals) / num_days,
            "by_day_part": day_part_counts,
            "mean_duration": sum(durations) / len(durations),
        }
