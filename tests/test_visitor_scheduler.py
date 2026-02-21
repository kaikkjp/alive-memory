"""Tests for sim.visitors.scheduler — Poisson arrival process.

Validates:
- Determinism: same seed → same arrival pattern
- Day-part modulation: lunch has more arrivals than evening
- Sleep exclusion: no arrivals during sleep window
- Scenario configs: isolation produces 0 visitors, stress produces more than standard
- Statistics: arrival counts are within expected Poisson bounds
"""

import pytest
from sim.visitors.scheduler import (
    VisitorScheduler,
    ScenarioConfig,
    SCENARIO_CONFIGS,
)
from sim.visitors.models import DayPart, VisitorTier


class TestDeterminism:
    """Same seed must produce identical schedules."""

    def test_same_seed_same_arrivals(self):
        s1 = VisitorScheduler(scenario="standard", seed=42)
        s2 = VisitorScheduler(scenario="standard", seed=42)
        a1 = s1.generate(num_cycles=1000)
        a2 = s2.generate(num_cycles=1000)

        assert len(a1) == len(a2)
        for x, y in zip(a1, a2):
            assert x.cycle == y.cycle
            assert x.visitor.visitor_id == y.visitor.visitor_id
            assert x.visitor.name == y.visitor.name
            assert x.day_part == y.day_part
            assert x.visit_duration_cycles == y.visit_duration_cycles

    def test_different_seed_different_arrivals(self):
        s1 = VisitorScheduler(scenario="standard", seed=42)
        s2 = VisitorScheduler(scenario="standard", seed=99)
        a1 = s1.generate(num_cycles=1000)
        a2 = s2.generate(num_cycles=1000)

        # Different seeds should produce different counts (very likely)
        # or at least different cycle patterns
        cycles1 = [a.cycle for a in a1]
        cycles2 = [a.cycle for a in a2]
        assert cycles1 != cycles2

    def test_determinism_across_runs(self):
        """Multiple calls to generate() with fresh schedulers must match."""
        results = []
        for _ in range(3):
            s = VisitorScheduler(scenario="standard", seed=123)
            arrivals = s.generate(num_cycles=500)
            results.append([(a.cycle, a.visitor.visitor_id) for a in arrivals])

        assert results[0] == results[1] == results[2]


class TestIsolationScenario:
    """Isolation scenario must produce zero visitors."""

    def test_no_visitors(self):
        s = VisitorScheduler(scenario="isolation", seed=42)
        arrivals = s.generate(num_cycles=1000)
        assert len(arrivals) == 0

    def test_stats_empty(self):
        s = VisitorScheduler(scenario="isolation", seed=42)
        arrivals = s.generate(num_cycles=1000)
        stats = s.stats(arrivals, 1000)
        assert stats["total_visitors"] == 0


class TestStandardScenario:
    """Standard scenario should produce reasonable visitor counts."""

    def test_visitor_count_in_range(self):
        """Expected: ~60-80 visitors per 1000 cycles per spec."""
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=1000)
        # Allow generous bounds for Poisson variance
        assert 30 <= len(arrivals) <= 150, (
            f"Expected 30-150 visitors, got {len(arrivals)}"
        )

    def test_visitors_are_tier1(self):
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=1000)
        for a in arrivals:
            assert a.visitor.tier == VisitorTier.TIER_1

    def test_visitor_ids_unique(self):
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=1000)
        ids = [a.visitor.visitor_id for a in arrivals]
        assert len(ids) == len(set(ids))


class TestStressScenario:
    """Stress scenario should produce more visitors than standard."""

    def test_more_visitors_than_standard(self):
        std = VisitorScheduler(scenario="standard", seed=42)
        stress = VisitorScheduler(scenario="stress", seed=42)
        a_std = std.generate(num_cycles=1000)
        a_stress = stress.generate(num_cycles=1000)
        assert len(a_stress) > len(a_std)


class TestDayPartModulation:
    """Arrivals should follow day-part distribution."""

    def test_lunch_more_than_evening(self):
        """Lunch multiplier (2.0) > evening multiplier (0.3)."""
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=2000)  # ~7 days for stats
        stats = s.stats(arrivals, 2000)

        lunch = stats["by_day_part"].get("lunch", 0)
        evening = stats["by_day_part"].get("evening", 0)
        # Lunch should have more arrivals than evening
        assert lunch > evening, (
            f"Lunch ({lunch}) should exceed evening ({evening})"
        )

    def test_all_day_parts_represented(self):
        """With enough cycles, all day parts should have arrivals."""
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=3000)  # ~10 days
        stats = s.stats(arrivals, 3000)

        for part in ["morning", "lunch", "afternoon", "evening"]:
            assert stats["by_day_part"].get(part, 0) > 0, (
                f"Day part '{part}' has no arrivals"
            )


class TestSleepExclusion:
    """No arrivals during sleep window (3AM-6AM JST)."""

    def test_no_arrivals_during_sleep(self):
        """Validate against the actual 3AM-6AM boundary, not derived math."""
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=1000)

        day_length = VisitorScheduler.CYCLES_PER_DAY

        for a in arrivals:
            cycle_in_day = a.cycle % day_length
            assert not (VisitorScheduler.SLEEP_START <= cycle_in_day < VisitorScheduler.SLEEP_END), (
                f"Arrival at cycle {a.cycle} falls in sleep window "
                f"(cycle_in_day={cycle_in_day}, "
                f"sleep={VisitorScheduler.SLEEP_START}-{VisitorScheduler.SLEEP_END})"
            )

    def test_sleep_constants_match_runner_timing(self):
        """Verify scheduler sleep window matches runner execution semantics.

        The runner advances the clock BEFORE processing each cycle, so
        the test must advance first then check — matching the real order
        in SimulationRunner.run().
        """
        from sim.clock import SimulatedClock

        clock = SimulatedClock(start="2026-02-01T09:00:00+09:00")

        for cycle in range(VisitorScheduler.CYCLES_PER_DAY):
            # Runner order: advance FIRST, then check sleep
            clock.advance(minutes=5)

            cycle_in_day = cycle % VisitorScheduler.CYCLES_PER_DAY
            scheduler_says_sleep = (
                VisitorScheduler.SLEEP_START <= cycle_in_day < VisitorScheduler.SLEEP_END
            )
            clock_says_sleep = clock.is_sleep_window

            assert scheduler_says_sleep == clock_says_sleep, (
                f"Cycle {cycle} (hour={clock.hour}): "
                f"scheduler={scheduler_says_sleep}, clock={clock_says_sleep}"
            )


class TestVisitorGeneration:
    """Visitor instances should have valid attributes."""

    def test_traits_in_range(self):
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=500)

        for a in arrivals:
            t = a.visitor.traits
            assert 0.0 <= t.patience <= 1.0
            assert 0.0 <= t.knowledge <= 1.0
            assert 0.0 <= t.budget <= 1.0
            assert 0.0 <= t.chattiness <= 1.0
            assert 0.0 <= t.collector_bias <= 1.0
            assert t.emotional_state in (
                "neutral", "curious", "excited", "nostalgic", "frustrated"
            )

    def test_visit_duration_bounds(self):
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=500)

        for a in arrivals:
            assert 2 <= a.visit_duration_cycles <= 12

    def test_visitor_has_goal(self):
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=500)

        valid_goals = {"buy", "sell", "browse", "learn", "chat", "appraise"}
        for a in arrivals:
            assert a.visitor.goal in valid_goals


class TestCustomConfig:
    """Custom ScenarioConfig should work."""

    def test_custom_base_rate(self):
        config = ScenarioConfig(name="custom", base_rate=0.5)
        s = VisitorScheduler(config=config, seed=42)
        arrivals = s.generate(num_cycles=500)
        # High base rate should produce many visitors
        assert len(arrivals) > 50

    def test_zero_base_rate(self):
        config = ScenarioConfig(name="empty", base_rate=0.0)
        s = VisitorScheduler(config=config, seed=42)
        arrivals = s.generate(num_cycles=500)
        assert len(arrivals) == 0


class TestArrivalsInRange:
    """Filter arrivals to cycle ranges."""

    def test_filter_range(self):
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=1000)
        filtered = s.arrivals_in_range(arrivals, 100, 200)
        for a in filtered:
            assert 100 <= a.cycle < 200

    def test_empty_range(self):
        s = VisitorScheduler(scenario="isolation", seed=42)
        arrivals = s.generate(num_cycles=1000)
        filtered = s.arrivals_in_range(arrivals, 100, 200)
        assert len(filtered) == 0


class TestScenarioConfigs:
    """All scenario presets should be valid."""

    def test_all_configs_exist(self):
        expected = {"isolation", "standard", "social", "stress", "returning"}
        assert expected == set(SCENARIO_CONFIGS.keys())

    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError):
            VisitorScheduler(scenario="nonexistent")

    @pytest.mark.parametrize("scenario", list(SCENARIO_CONFIGS.keys()))
    def test_generate_all_scenarios(self, scenario):
        """Every scenario config should generate without error."""
        s = VisitorScheduler(scenario=scenario, seed=42)
        arrivals = s.generate(num_cycles=500)
        assert isinstance(arrivals, list)
