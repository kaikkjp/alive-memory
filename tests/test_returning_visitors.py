"""Tests for Tier 3 returning visitor scheduling and N3 memory scoring.

Covers:
- ReturningVisitorManager: flagging, return scheduling, memory stubs,
  determinism, horizon distribution, cycle bounds
- MemoryScorer: visit recording, N3 metric computation, identity recall,
  transaction recall, preference continuity, depth gradient
- Integration with VisitorScheduler (Tier 3 arrivals in returning scenario)
"""

from __future__ import annotations

import random

import pytest

from sim.visitors.models import (
    DayPart,
    ReturnPlan,
    ScheduledArrival,
    VisitSummary,
    VisitorInstance,
    VisitorTier,
    VisitorTraits,
)
from sim.visitors.returning import (
    HORIZON_WEIGHTS,
    RETURN_ENTERING_TEMPLATES,
    RETURN_HORIZONS,
    ReturningVisitorManager,
)
from sim.visitors.scheduler import VisitorScheduler
from sim.metrics.memory_score import MemoryScorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_arrival(
    visitor_id: str = "sim:visitor_0001",
    name: str = "Tanaka-san",
    cycle: int = 50,
    duration: int = 6,
    goal: str = "buy",
    archetype_id: str = "regular_tanaka",
    tier: VisitorTier = VisitorTier.TIER_1,
    emotional_state: str = "neutral",
) -> ScheduledArrival:
    """Create a test ScheduledArrival."""
    visitor = VisitorInstance(
        visitor_id=visitor_id,
        tier=tier,
        archetype_id=archetype_id,
        name=name,
        traits=VisitorTraits(
            patience=0.8, knowledge=0.6, budget=0.5,
            chattiness=0.7, emotional_state=emotional_state,
        ),
        goal=goal,
    )
    return ScheduledArrival(
        cycle=cycle,
        visitor=visitor,
        day_part=DayPart.AFTERNOON,
        visit_duration_cycles=duration,
    )


def _make_arrivals(count: int, start_cycle: int = 10) -> list[ScheduledArrival]:
    """Create a batch of test arrivals with unique IDs."""
    arrivals = []
    for i in range(count):
        arrivals.append(_make_arrival(
            visitor_id=f"sim:visitor_{i:04d}",
            name=f"Visitor-{i}",
            cycle=start_cycle + i * 20,
            archetype_id="regular_tanaka",
        ))
    return arrivals


# ---------------------------------------------------------------------------
# ReturningVisitorManager — Flagging
# ---------------------------------------------------------------------------

class TestFlagging:
    """Test that visitors are flagged for return at the correct rate."""

    def test_return_rate_approximate(self):
        """~30% of visitors should be flagged with return_rate=0.3."""
        mgr = ReturningVisitorManager(return_rate=0.3, seed=42)
        arrivals = _make_arrivals(100)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        # With 100 visitors and 30% rate, expect ~30 flagged
        # (some may be out of cycle range, so check flagged_count)
        assert 15 <= mgr.flagged_count <= 45

    def test_return_rate_zero_means_no_returns(self):
        """return_rate=0 → no visitors flagged."""
        mgr = ReturningVisitorManager(return_rate=0.0, seed=42)
        arrivals = _make_arrivals(50)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)
        assert len(returns) == 0
        assert mgr.flagged_count == 0

    def test_return_rate_one_flags_all(self):
        """return_rate=1.0 → every visitor flagged."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(20, start_cycle=10)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)
        assert mgr.flagged_count == 20

    def test_no_double_flagging(self):
        """Running schedule_returns twice doesn't re-flag visitors."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(10)
        r1 = mgr.schedule_returns(arrivals, num_cycles=5000)
        r2 = mgr.schedule_returns(arrivals, num_cycles=5000)
        assert len(r2) == 0  # Already flagged, no new returns


# ---------------------------------------------------------------------------
# ReturningVisitorManager — Scheduling
# ---------------------------------------------------------------------------

class TestScheduling:
    """Test return visit scheduling — cycle offsets, bounds, sorting."""

    def test_returns_sorted_by_cycle(self):
        """Return arrivals should be sorted by cycle."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(20)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)
        cycles = [r.cycle for r in returns]
        assert cycles == sorted(cycles)

    def test_return_cycle_after_initial_visit(self):
        """Return cycle must be after the initial visit ends."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(10)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        for ret, orig in zip(returns, arrivals):
            initial_end = orig.cycle + orig.visit_duration_cycles
            assert ret.cycle > initial_end, (
                f"Return at cycle {ret.cycle} should be after "
                f"initial visit end at cycle {initial_end}"
            )

    def test_returns_within_num_cycles(self):
        """No return visit should happen after num_cycles."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(10, start_cycle=10)
        returns = mgr.schedule_returns(arrivals, num_cycles=200)

        for r in returns:
            assert r.cycle < 200

    def test_returns_dropped_when_past_end(self):
        """Returns beyond num_cycles are silently dropped."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        # All arrivals late — returns will exceed 100 cycles
        arrivals = _make_arrivals(5, start_cycle=80)
        returns = mgr.schedule_returns(arrivals, num_cycles=100)

        # At cycle 80 + duration 6 + min_offset 50 = 136 > 100
        assert len(returns) == 0

    def test_return_offset_within_horizon(self):
        """Return offset should fall within the assigned horizon range."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [_make_arrival(cycle=10, duration=5)]
        returns = mgr.schedule_returns(arrivals, num_cycles=10000)

        if returns:
            ret = returns[0]
            plan = ret.visitor.return_plan
            initial_end = 10 + 5
            offset = ret.cycle - initial_end
            min_c, max_c = RETURN_HORIZONS[plan.horizon]
            assert min_c <= offset <= max_c, (
                f"Offset {offset} outside horizon '{plan.horizon}' "
                f"range [{min_c}, {max_c}]"
            )


# ---------------------------------------------------------------------------
# ReturningVisitorManager — Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Test that return scheduling is deterministic given the same seed."""

    def test_same_seed_same_returns(self):
        """Same seed → identical return arrivals."""
        arrivals = _make_arrivals(30)

        mgr1 = ReturningVisitorManager(return_rate=0.3, seed=42)
        r1 = mgr1.schedule_returns(arrivals, num_cycles=5000)

        mgr2 = ReturningVisitorManager(return_rate=0.3, seed=42)
        r2 = mgr2.schedule_returns(arrivals, num_cycles=5000)

        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a.cycle == b.cycle
            assert a.visitor.visitor_id == b.visitor.visitor_id
            assert a.visitor.memory_stub == b.visitor.memory_stub

    def test_different_seed_different_returns(self):
        """Different seeds → different return patterns."""
        arrivals = _make_arrivals(30)

        mgr1 = ReturningVisitorManager(return_rate=0.3, seed=42)
        r1 = mgr1.schedule_returns(arrivals, num_cycles=5000)

        mgr2 = ReturningVisitorManager(return_rate=0.3, seed=99)
        r2 = mgr2.schedule_returns(arrivals, num_cycles=5000)

        # Should differ in at least count or cycles
        ids1 = {r.visitor.visitor_id for r in r1}
        ids2 = {r.visitor.visitor_id for r in r2}
        assert ids1 != ids2 or len(r1) != len(r2)


# ---------------------------------------------------------------------------
# ReturningVisitorManager — Memory Stubs
# ---------------------------------------------------------------------------

class TestMemoryStubs:
    """Test memory stub generation for returning visitors."""

    def test_memory_stub_populated(self):
        """Return visitors should have a non-empty memory_stub."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(5)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        for r in returns:
            assert r.visitor.memory_stub is not None
            assert len(r.visitor.memory_stub) > 10

    def test_memory_stub_contains_name(self):
        """Memory stub should mention the visitor's name."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [_make_arrival(name="Tanaka-san")]
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        if returns:
            assert "Tanaka-san" in returns[0].visitor.memory_stub

    def test_memory_stub_contains_goal_context(self):
        """Memory stub should reference the visitor's original goal."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [_make_arrival(goal="sell")]
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        if returns:
            assert "sell" in returns[0].visitor.memory_stub.lower()

    def test_memory_stub_contains_emotion(self):
        """Memory stub should mention the visitor's emotional state."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [_make_arrival(emotional_state="excited")]
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        if returns:
            assert "excited" in returns[0].visitor.memory_stub

    def test_memory_stubs_dict(self):
        """Manager tracks all memory stubs by visitor ID."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(5)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        stubs = mgr.memory_stubs
        for r in returns:
            assert r.visitor.visitor_id in stubs


# ---------------------------------------------------------------------------
# ReturningVisitorManager — Return Visit Properties
# ---------------------------------------------------------------------------

class TestReturnVisitProperties:
    """Test properties of generated return visit arrivals."""

    def test_tier_3(self):
        """Return visitors should be Tier 3."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(5)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        for r in returns:
            assert r.visitor.tier == VisitorTier.TIER_3

    def test_same_visitor_id(self):
        """Return visitors keep the same visitor_id."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(5)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        original_ids = {a.visitor.visitor_id for a in arrivals}
        for r in returns:
            assert r.visitor.visitor_id in original_ids

    def test_same_archetype(self):
        """Return visitors keep the same archetype_id."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(5)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        for r in returns:
            assert r.visitor.archetype_id == "regular_tanaka"

    def test_visit_history_populated(self):
        """Return visitors should have non-empty visit_history."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(5)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        for r in returns:
            assert len(r.visitor.visit_history) >= 1
            assert r.visitor.visit_history[0].visit_id.endswith("_v0")

    def test_return_plan_populated(self):
        """Return visitors should have a populated return plan."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(5)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        for r in returns:
            plan = r.visitor.return_plan
            assert plan.will_return is True
            assert plan.horizon in RETURN_HORIZONS

    def test_visit_duration_bounded(self):
        """Return visit duration should be in [2, 12]."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(20)
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)

        for r in returns:
            assert 2 <= r.visit_duration_cycles <= 12


# ---------------------------------------------------------------------------
# ReturningVisitorManager — Return Entering Text
# ---------------------------------------------------------------------------

class TestReturnEnteringText:
    """Test return-visit entering dialogue generation."""

    def test_entering_text_non_empty(self):
        """Return entering text should be non-empty."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        visitor = VisitorInstance(
            visitor_id="sim:test",
            tier=VisitorTier.TIER_3,
            name="Test",
            goal="buy",
            visit_history=[VisitSummary(
                visit_id="v0", start_cycle=10, end_cycle=20,
                exit_reason="completed", turns=5,
            )],
        )
        rng = random.Random(42)
        text = mgr.get_return_entering_text(visitor, rng)
        assert len(text) > 10

    def test_entering_text_deterministic(self):
        """Same seed → same entering text."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        visitor = VisitorInstance(
            visitor_id="sim:test",
            tier=VisitorTier.TIER_3,
            name="Test",
            goal="browse",
            visit_history=[VisitSummary(
                visit_id="v0", start_cycle=10, end_cycle=20,
                exit_reason="natural", turns=5,
            )],
        )
        t1 = mgr.get_return_entering_text(visitor, random.Random(42))
        t2 = mgr.get_return_entering_text(visitor, random.Random(42))
        assert t1 == t2

    def test_entering_text_without_history_has_fallback(self):
        """Visitor with no history gets a fallback message."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        visitor = VisitorInstance(
            visitor_id="sim:test",
            tier=VisitorTier.TIER_3,
            name="Test",
        )
        text = mgr.get_return_entering_text(visitor, random.Random(42))
        assert "before" in text.lower() or "again" in text.lower()


# ---------------------------------------------------------------------------
# Horizon Distribution
# ---------------------------------------------------------------------------

class TestHorizonDistribution:
    """Test that horizon selection covers all three categories."""

    def test_all_horizons_represented(self):
        """With enough visitors, all three horizons should appear."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = _make_arrivals(50, start_cycle=10)
        returns = mgr.schedule_returns(arrivals, num_cycles=10000)

        horizons = {r.visitor.return_plan.horizon for r in returns}
        assert "short" in horizons
        assert "medium" in horizons
        # "long" may not appear with only 50 visitors at 15% weight,
        # so we test it's at least a valid horizon
        for h in horizons:
            assert h in RETURN_HORIZONS


# ---------------------------------------------------------------------------
# MemoryScorer
# ---------------------------------------------------------------------------

class TestMemoryScorer:
    """Test N3 memory score computation."""

    def test_empty_scorer_returns_zeros(self):
        """No visits → all zeros."""
        scorer = MemoryScorer()
        n3 = scorer.compute_n3()
        assert n3["identity_recall_rate"] == 0.0
        assert n3["transaction_recall_rate"] == 0.0
        assert n3["preference_continuity"] == 0.0
        assert n3["depth_gradient"] == 0.0
        assert n3["total_return_visits"] == 0
        assert n3["total_returning_visitors"] == 0

    def test_no_return_visits_returns_zeros(self):
        """Only initial visits (no returns) → zeros."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=False, goal="buy", turn_count=5,
        )
        n3 = scorer.compute_n3()
        assert n3["total_return_visits"] == 0

    def test_identity_recall_detected(self):
        """Shopkeeper dialogue with recognition keywords → identity recalled."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Tanaka",
            is_return=False, goal="buy", turn_count=5,
        )
        scorer.record_visit(
            visitor_id="v1", visitor_name="Tanaka",
            is_return=True, goal="buy", turn_count=6,
            shopkeeper_dialogues=["Welcome back, Tanaka. Good to see you again."],
            memory_stub="Tanaka came to buy cards.",
        )
        n3 = scorer.compute_n3()
        assert n3["identity_recall_rate"] == 1.0

    def test_identity_recall_by_name(self):
        """Using the visitor's name counts as identity recall."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Suzuki",
            is_return=False, goal="browse", turn_count=3,
        )
        scorer.record_visit(
            visitor_id="v1", visitor_name="Suzuki",
            is_return=True, goal="browse", turn_count=4,
            shopkeeper_dialogues=["Oh, Suzuki. Looking around today?"],
        )
        n3 = scorer.compute_n3()
        assert n3["identity_recall_rate"] == 1.0

    def test_no_identity_recall(self):
        """Generic dialogue without recognition → identity not recalled."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Yamada",
            is_return=False, goal="buy", turn_count=5,
        )
        scorer.record_visit(
            visitor_id="v1", visitor_name="Yamada",
            is_return=True, goal="buy", turn_count=5,
            shopkeeper_dialogues=["Hello. What can I help you with?"],
        )
        n3 = scorer.compute_n3()
        assert n3["identity_recall_rate"] == 0.0

    def test_transaction_recall_detected(self):
        """Dialogue mentioning purchases → transaction recalled."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=False, goal="buy", turn_count=5,
        )
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=True, goal="buy", turn_count=5,
            shopkeeper_dialogues=["I remember the card you bought last time."],
        )
        n3 = scorer.compute_n3()
        assert n3["transaction_recall_rate"] == 1.0

    def test_preference_continuity_same_goal(self):
        """Returning with the same goal → continuity = 1.0."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=False, goal="buy", turn_count=5,
        )
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=True, goal="buy", turn_count=5,
        )
        n3 = scorer.compute_n3()
        assert n3["preference_continuity"] == 1.0

    def test_preference_continuity_different_goal(self):
        """Returning with a different goal → continuity = 0.0."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=False, goal="buy", turn_count=5,
        )
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=True, goal="browse", turn_count=5,
        )
        n3 = scorer.compute_n3()
        assert n3["preference_continuity"] == 0.0

    def test_depth_gradient_increasing(self):
        """More turns on return → depth_gradient > 1."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=False, goal="buy", turn_count=4,
        )
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=True, goal="buy", turn_count=8,
        )
        n3 = scorer.compute_n3()
        assert n3["depth_gradient"] == 2.0

    def test_depth_gradient_decreasing(self):
        """Fewer turns on return → depth_gradient < 1."""
        scorer = MemoryScorer()
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=False, goal="buy", turn_count=8,
        )
        scorer.record_visit(
            visitor_id="v1", visitor_name="Test",
            is_return=True, goal="buy", turn_count=4,
        )
        n3 = scorer.compute_n3()
        assert n3["depth_gradient"] == 0.5

    def test_multiple_returning_visitors(self):
        """Score aggregates across multiple returning visitors."""
        scorer = MemoryScorer()
        # Visitor 1: recognized
        scorer.record_visit("v1", "Alice", False, "buy", 5)
        scorer.record_visit(
            "v1", "Alice", True, "buy", 5,
            shopkeeper_dialogues=["Welcome back, Alice."],
        )
        # Visitor 2: not recognized
        scorer.record_visit("v2", "Bob", False, "browse", 3)
        scorer.record_visit(
            "v2", "Bob", True, "browse", 3,
            shopkeeper_dialogues=["Hello."],
        )
        n3 = scorer.compute_n3()
        assert n3["identity_recall_rate"] == 0.5
        assert n3["total_return_visits"] == 2
        assert n3["total_returning_visitors"] == 2

    def test_visit_count_tracking(self):
        """Scorer tracks total visit count correctly."""
        scorer = MemoryScorer()
        scorer.record_visit("v1", "A", False, "buy", 5)
        scorer.record_visit("v1", "A", True, "buy", 6)
        scorer.record_visit("v2", "B", False, "browse", 3)
        assert scorer.visit_count == 3

    def test_returning_visitor_ids(self):
        """returning_visitor_ids only includes visitors with returns."""
        scorer = MemoryScorer()
        scorer.record_visit("v1", "A", False, "buy", 5)
        scorer.record_visit("v1", "A", True, "buy", 6)
        scorer.record_visit("v2", "B", False, "browse", 3)
        assert scorer.returning_visitor_ids == {"v1"}


# ---------------------------------------------------------------------------
# Integration: Scheduler + ReturningVisitorManager
# ---------------------------------------------------------------------------

class TestSchedulerIntegration:
    """Test that ReturningVisitorManager works with real scheduler output."""

    def test_returning_scenario_produces_returns(self):
        """The 'returning' scenario with scheduler output should generate returns."""
        scheduler = VisitorScheduler(scenario="returning", seed=42)
        arrivals = scheduler.generate(num_cycles=1000)

        # The returning scenario has tier3_return_rate=0.3
        mgr = ReturningVisitorManager(return_rate=0.3, seed=42)
        returns = mgr.schedule_returns(arrivals, num_cycles=1000)

        # With ~60-80 initial visitors and 30% flag rate, expect some returns
        # (many may be beyond 1000 cycles though)
        assert mgr.flagged_count > 0

    def test_standard_scenario_no_tier3(self):
        """Standard scenario visitors can still be processed (but config won't enable it)."""
        scheduler = VisitorScheduler(scenario="standard", seed=42)
        arrivals = scheduler.generate(num_cycles=1000)

        # Zero return rate → no returns
        mgr = ReturningVisitorManager(return_rate=0.0, seed=42)
        returns = mgr.schedule_returns(arrivals, num_cycles=1000)
        assert len(returns) == 0

    def test_return_visitors_have_valid_day_parts(self):
        """Return visit day parts should be valid DayPart values."""
        scheduler = VisitorScheduler(scenario="returning", seed=42)
        arrivals = scheduler.generate(num_cycles=2000)

        mgr = ReturningVisitorManager(return_rate=0.5, seed=42)
        returns = mgr.schedule_returns(arrivals, num_cycles=2000)

        valid_parts = {DayPart.MORNING, DayPart.LUNCH, DayPart.AFTERNOON, DayPart.EVENING}
        for r in returns:
            assert r.day_part in valid_parts

    def test_no_overlap_with_initial_arrivals(self):
        """Return visits should not collide with the same visitor's initial visit."""
        scheduler = VisitorScheduler(scenario="returning", seed=42)
        arrivals = scheduler.generate(num_cycles=2000)

        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        returns = mgr.schedule_returns(arrivals, num_cycles=2000)

        # Build initial visit ranges
        visit_ranges: dict[str, tuple[int, int]] = {}
        for a in arrivals:
            vid = a.visitor.visitor_id
            visit_ranges[vid] = (a.cycle, a.cycle + a.visit_duration_cycles)

        for r in returns:
            vid = r.visitor.visitor_id
            if vid in visit_ranges:
                _, initial_end = visit_ranges[vid]
                assert r.cycle > initial_end
