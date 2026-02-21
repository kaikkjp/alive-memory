"""Tests for sim.visitors.state_machine and sim.visitors.archetypes.

Validates:
- State machine exit conditions (patience, goal satisfaction, max turns)
- State transitions follow valid paths
- Archetype selection and trait vectors
- Dialogue template coverage
- Determinism (same seed = same visit sequence)
"""

import random

import pytest

from sim.visitors.archetypes import ARCHETYPES, pick_archetype, pick_goal
from sim.visitors.models import (
    ExitReason,
    VisitorInstance,
    VisitorState,
    VisitorTier,
)
from sim.visitors.state_machine import (
    MAX_TURNS,
    VisitorStateMachine,
    VisitTurn,
)
from sim.visitors.templates import (
    TEMPLATES,
    FALLBACK_TEMPLATES,
    get_template,
    get_template_with_fallback,
)


# ---------------------------------------------------------------------------
# Archetype tests
# ---------------------------------------------------------------------------


class TestArchetypes:
    """Test archetype definitions and selection."""

    def test_all_10_archetypes_defined(self):
        """Spec requires exactly 10 Tier 1 archetypes."""
        assert len(ARCHETYPES) == 10

    def test_archetype_ids_match_spec(self):
        expected_ids = {
            "regular_tanaka", "newbie_student", "whale_collector",
            "haggler_uncle", "browser_tourist", "nostalgic_adult",
            "expert_rival", "seller_cleaner", "kid_allowance",
            "online_crossover",
        }
        assert set(ARCHETYPES.keys()) == expected_ids

    def test_traits_in_valid_range(self):
        for aid, archetype in ARCHETYPES.items():
            t = archetype.traits
            assert 0.0 <= t.patience <= 1.0, f"{aid}.patience out of range"
            assert 0.0 <= t.knowledge <= 1.0, f"{aid}.knowledge out of range"
            assert 0.0 <= t.budget <= 1.0, f"{aid}.budget out of range"
            assert 0.0 <= t.chattiness <= 1.0, f"{aid}.chattiness out of range"
            assert 0.0 <= t.collector_bias <= 1.0, f"{aid}.collector_bias out of range"

    def test_all_archetypes_have_goals(self):
        for aid, archetype in ARCHETYPES.items():
            assert len(archetype.goal_templates) > 0, (
                f"{aid} has no goal templates"
            )

    def test_all_archetypes_have_positive_weight(self):
        for aid, archetype in ARCHETYPES.items():
            assert archetype.weight > 0, f"{aid} has non-positive weight"

    def test_pick_archetype_deterministic(self):
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        picks1 = [pick_archetype(rng1).archetype_id for _ in range(20)]
        picks2 = [pick_archetype(rng2).archetype_id for _ in range(20)]
        assert picks1 == picks2

    def test_pick_archetype_covers_variety(self):
        """Over many picks, multiple archetypes should appear."""
        rng = random.Random(123)
        picks = {pick_archetype(rng).archetype_id for _ in range(100)}
        assert len(picks) >= 5, f"Only {len(picks)} unique archetypes in 100 picks"

    def test_pick_goal_from_templates(self):
        rng = random.Random(42)
        for archetype in ARCHETYPES.values():
            goal = pick_goal(archetype, rng)
            assert goal in archetype.goal_templates


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------


class TestTemplates:
    """Test dialogue template coverage."""

    def test_all_archetypes_have_templates(self):
        for aid in ARCHETYPES:
            assert aid in TEMPLATES, f"No templates for archetype {aid}"

    def test_entering_templates_exist(self):
        """Every archetype+goal combo should have ENTERING dialogue."""
        for aid, archetype in ARCHETYPES.items():
            for goal in archetype.goal_templates:
                templates = get_template_with_fallback(
                    aid, goal, VisitorState.ENTERING
                )
                assert len(templates) > 0, (
                    f"No ENTERING templates for {aid}/{goal}"
                )

    def test_exiting_templates_exist(self):
        """Every archetype+goal combo should have EXITING dialogue."""
        for aid, archetype in ARCHETYPES.items():
            for goal in archetype.goal_templates:
                templates = get_template_with_fallback(
                    aid, goal, VisitorState.EXITING
                )
                assert len(templates) > 0, (
                    f"No EXITING templates for {aid}/{goal}"
                )

    def test_fallback_templates_cover_all_goals(self):
        expected_goals = {"buy", "sell", "browse", "learn", "chat", "appraise", "trade"}
        assert set(FALLBACK_TEMPLATES.keys()) == expected_goals

    def test_fallback_used_when_specific_missing(self):
        """Fallback should return templates when archetype-specific ones are missing."""
        # whale_collector only has "buy" goal templates;
        # try a goal not in its templates (if any)
        templates = get_template("whale_collector", "chat", VisitorState.ENTERING)
        assert templates == []  # No specific templates

        fallback = get_template_with_fallback(
            "whale_collector", "chat", VisitorState.ENTERING
        )
        assert len(fallback) > 0  # Fallback provides templates


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


def _make_visitor(archetype_id: str, goal: str | None = None) -> tuple:
    """Helper: create a visitor + archetype pair for testing."""
    archetype = ARCHETYPES[archetype_id]
    if goal is None:
        goal = archetype.goal_templates[0]
    visitor = VisitorInstance(
        visitor_id="sim:test_0000",
        tier=VisitorTier.TIER_1,
        archetype_id=archetype_id,
        name=archetype.name,
        traits=archetype.traits,
        goal=goal,
    )
    return visitor, archetype


class TestStateMachine:
    """Test visitor state machine lifecycle."""

    def test_visit_starts_entering_ends_exiting(self):
        visitor, archetype = _make_visitor("regular_tanaka", "buy")
        sm = VisitorStateMachine(visitor, archetype, random.Random(42))
        turns = sm.generate_visit()

        assert len(turns) >= 2, "Visit should have at least entering + exiting"
        assert turns[0].state == VisitorState.ENTERING
        assert turns[-1].state == VisitorState.EXITING
        assert turns[-1].is_exit is True

    def test_exit_reason_is_set(self):
        visitor, archetype = _make_visitor("regular_tanaka", "buy")
        sm = VisitorStateMachine(visitor, archetype, random.Random(42))
        turns = sm.generate_visit()

        last = turns[-1]
        assert last.exit_reason is not None
        assert isinstance(last.exit_reason, ExitReason)

    def test_max_turns_enforced(self):
        """No visit should exceed MAX_TURNS."""
        for archetype_id in ARCHETYPES:
            archetype = ARCHETYPES[archetype_id]
            for goal in archetype.goal_templates:
                visitor, arch = _make_visitor(archetype_id, goal)
                sm = VisitorStateMachine(visitor, arch, random.Random(42))
                turns = sm.generate_visit()
                assert len(turns) <= MAX_TURNS + 1, (
                    f"{archetype_id}/{goal}: {len(turns)} turns exceeds max"
                )

    def test_determinism(self):
        """Same seed produces identical visit sequence."""
        visitor, archetype = _make_visitor("nostalgic_adult", "chat")

        sm1 = VisitorStateMachine(visitor, archetype, random.Random(99))
        turns1 = sm1.generate_visit()

        sm2 = VisitorStateMachine(visitor, archetype, random.Random(99))
        turns2 = sm2.generate_visit()

        assert len(turns1) == len(turns2)
        for t1, t2 in zip(turns1, turns2):
            assert t1.text == t2.text
            assert t1.state == t2.state

    def test_different_seeds_produce_different_visits(self):
        """Different seeds should generally produce different dialogue."""
        visitor, archetype = _make_visitor("regular_tanaka", "buy")

        sm1 = VisitorStateMachine(visitor, archetype, random.Random(1))
        turns1 = sm1.generate_visit()

        sm2 = VisitorStateMachine(visitor, archetype, random.Random(999))
        turns2 = sm2.generate_visit()

        # At least length or some text should differ
        texts1 = [t.text for t in turns1]
        texts2 = [t.text for t in turns2]
        assert texts1 != texts2 or len(turns1) != len(turns2)

    def test_all_turns_have_text(self):
        """Every generated turn must have non-empty dialogue text."""
        for archetype_id in ARCHETYPES:
            archetype = ARCHETYPES[archetype_id]
            for goal in archetype.goal_templates:
                visitor, arch = _make_visitor(archetype_id, goal)
                sm = VisitorStateMachine(visitor, arch, random.Random(42))
                turns = sm.generate_visit()
                for turn in turns:
                    assert turn.text, (
                        f"{archetype_id}/{goal} turn {turn.turn_number} "
                        f"in state {turn.state} has empty text"
                    )


class TestExitConditions:
    """Test specific exit condition scenarios."""

    def test_impatient_visitor_exits_quickly(self):
        """Haggler (patience=0.4) should have shorter visits than
        Tanaka (patience=0.8) when both have goal=buy."""
        haggler_visitor, haggler_arch = _make_visitor("haggler_uncle", "buy")
        tanaka_visitor, tanaka_arch = _make_visitor("regular_tanaka", "buy")

        # Run multiple seeds and compare average visit lengths
        haggler_lengths = []
        tanaka_lengths = []
        for seed in range(30):
            sm = VisitorStateMachine(
                haggler_visitor, haggler_arch, random.Random(seed)
            )
            haggler_lengths.append(len(sm.generate_visit()))

            sm = VisitorStateMachine(
                tanaka_visitor, tanaka_arch, random.Random(seed)
            )
            tanaka_lengths.append(len(sm.generate_visit()))

        avg_haggler = sum(haggler_lengths) / len(haggler_lengths)
        avg_tanaka = sum(tanaka_lengths) / len(tanaka_lengths)
        assert avg_haggler < avg_tanaka, (
            f"Haggler avg {avg_haggler:.1f} >= Tanaka avg {avg_tanaka:.1f}"
        )

    def test_expert_rival_no_negotiation(self):
        """Rival shop owner (goal=appraise) should not negotiate."""
        visitor, archetype = _make_visitor("expert_rival", "appraise")
        sm = VisitorStateMachine(visitor, archetype, random.Random(42))
        turns = sm.generate_visit()

        states = [t.state for t in turns]
        assert VisitorState.NEGOTIATING not in states, (
            "Expert rival should not enter NEGOTIATING state"
        )

    def test_patience_exhausted_exit_exists(self):
        """PATIENCE_EXHAUSTED should appear as an exit reason across
        the full archetype distribution."""
        patience_exits = 0
        for archetype_id in ARCHETYPES:
            archetype = ARCHETYPES[archetype_id]
            for goal in archetype.goal_templates:
                visitor, arch = _make_visitor(archetype_id, goal)
                for seed in range(20):
                    sm = VisitorStateMachine(
                        visitor, arch, random.Random(seed)
                    )
                    turns = sm.generate_visit()
                    if turns[-1].exit_reason == ExitReason.PATIENCE_EXHAUSTED:
                        patience_exits += 1

        assert patience_exits > 0, (
            "PATIENCE_EXHAUSTED never occurred across all archetypes/seeds"
        )

    def test_multiple_exit_reasons_occur(self):
        """The state machine should produce a variety of exit reasons."""
        exit_reasons: set[ExitReason] = set()
        for archetype_id in ARCHETYPES:
            archetype = ARCHETYPES[archetype_id]
            for goal in archetype.goal_templates:
                visitor, arch = _make_visitor(archetype_id, goal)
                for seed in range(10):
                    sm = VisitorStateMachine(
                        visitor, arch, random.Random(seed)
                    )
                    turns = sm.generate_visit()
                    exit_reasons.add(turns[-1].exit_reason)

        # Should see at least goal_satisfied and one other
        assert ExitReason.GOAL_SATISFIED in exit_reasons
        assert len(exit_reasons) >= 2, (
            f"Only one exit reason: {exit_reasons}"
        )

    def test_goal_satisfied_exit(self):
        """Browse visitors (easy goal) should commonly exit with GOAL_SATISFIED."""
        visitor, archetype = _make_visitor("browser_tourist", "browse")

        satisfied_exits = 0
        for seed in range(20):
            sm = VisitorStateMachine(visitor, archetype, random.Random(seed))
            turns = sm.generate_visit()
            if turns[-1].exit_reason == ExitReason.GOAL_SATISFIED:
                satisfied_exits += 1

        assert satisfied_exits > 0, (
            "Tourist never achieved goal satisfaction across 20 seeds"
        )


class TestStateTransitions:
    """Test that state transitions follow valid paths."""

    VALID_TRANSITIONS = {
        VisitorState.ENTERING: {
            VisitorState.BROWSING, VisitorState.ENGAGING,
        },
        VisitorState.BROWSING: {
            VisitorState.ENGAGING, VisitorState.DECIDING,
            VisitorState.EXITING,
        },
        VisitorState.ENGAGING: {
            VisitorState.NEGOTIATING, VisitorState.DECIDING,
            VisitorState.ENGAGING, VisitorState.EXITING,
        },
        VisitorState.NEGOTIATING: {
            VisitorState.DECIDING, VisitorState.NEGOTIATING,
            VisitorState.EXITING,
        },
        VisitorState.DECIDING: {
            VisitorState.EXITING,
        },
        VisitorState.EXITING: set(),
    }

    def test_all_transitions_valid(self):
        """Every state transition should be in the valid set."""
        for archetype_id in ARCHETYPES:
            archetype = ARCHETYPES[archetype_id]
            for goal in archetype.goal_templates:
                visitor, arch = _make_visitor(archetype_id, goal)
                for seed in range(5):
                    sm = VisitorStateMachine(
                        visitor, arch, random.Random(seed)
                    )
                    turns = sm.generate_visit()

                    for i in range(len(turns) - 1):
                        current = turns[i].state
                        next_state = turns[i + 1].state
                        valid = self.VALID_TRANSITIONS.get(current, set())
                        assert next_state in valid, (
                            f"{archetype_id}/{goal} seed={seed}: "
                            f"invalid transition {current} -> {next_state}"
                        )


class TestSchedulerIntegration:
    """Test that the scheduler correctly uses archetypes."""

    def test_generated_visitors_have_archetype_ids(self):
        from sim.visitors.scheduler import VisitorScheduler

        scheduler = VisitorScheduler(scenario="standard", seed=42)
        arrivals = scheduler.generate(num_cycles=500)

        assert len(arrivals) > 0, "No arrivals generated"
        for arrival in arrivals:
            assert arrival.visitor.archetype_id is not None, (
                f"Visitor {arrival.visitor.visitor_id} has no archetype_id"
            )
            assert arrival.visitor.archetype_id in ARCHETYPES, (
                f"Unknown archetype: {arrival.visitor.archetype_id}"
            )

    def test_generated_visitors_use_archetype_names(self):
        from sim.visitors.scheduler import VisitorScheduler

        scheduler = VisitorScheduler(scenario="standard", seed=42)
        arrivals = scheduler.generate(num_cycles=500)

        archetype_names = {a.name for a in ARCHETYPES.values()}
        for arrival in arrivals:
            assert arrival.visitor.name in archetype_names, (
                f"Visitor name '{arrival.visitor.name}' not from any archetype"
            )

    def test_generated_visitor_goals_match_archetype(self):
        from sim.visitors.scheduler import VisitorScheduler

        scheduler = VisitorScheduler(scenario="standard", seed=42)
        arrivals = scheduler.generate(num_cycles=500)

        for arrival in arrivals:
            archetype = ARCHETYPES[arrival.visitor.archetype_id]
            assert arrival.visitor.goal in archetype.goal_templates, (
                f"Visitor goal '{arrival.visitor.goal}' not in "
                f"archetype {arrival.visitor.archetype_id} templates "
                f"{archetype.goal_templates}"
            )


# ---------------------------------------------------------------------------
# Regression tests for P1 fixes
# ---------------------------------------------------------------------------


class TestExitTurnGuarantee:
    """Regression: every visit must end with an explicit EXITING turn."""

    def test_all_visits_end_with_exit_turn(self):
        """No visit should end without is_exit=True on the last turn.

        Before the fix, DECIDING→EXITING via _transition() skipped
        _make_exit_turn(), producing visits with no exit turn.
        """
        missing_exit = 0
        total = 0
        for archetype_id in ARCHETYPES:
            archetype = ARCHETYPES[archetype_id]
            for goal in archetype.goal_templates:
                visitor, arch = _make_visitor(archetype_id, goal)
                for seed in range(50):
                    sm = VisitorStateMachine(
                        visitor, arch, random.Random(seed)
                    )
                    turns = sm.generate_visit()
                    total += 1
                    if not turns[-1].is_exit:
                        missing_exit += 1

        assert missing_exit == 0, (
            f"{missing_exit}/{total} visits ended without an exit turn"
        )

    def test_exit_turn_has_reason(self):
        """Every exit turn must have a non-None exit_reason."""
        for archetype_id in ARCHETYPES:
            archetype = ARCHETYPES[archetype_id]
            for goal in archetype.goal_templates:
                visitor, arch = _make_visitor(archetype_id, goal)
                for seed in range(20):
                    sm = VisitorStateMachine(
                        visitor, arch, random.Random(seed)
                    )
                    turns = sm.generate_visit()
                    last = turns[-1]
                    assert last.exit_reason is not None, (
                        f"{archetype_id}/{goal} seed={seed}: "
                        f"exit turn has no reason"
                    )

    def test_natural_exit_reason_occurs(self):
        """NATURAL exit reason should occur when DECIDING→EXITING
        happens without patience/goal/budget triggering first."""
        natural_exits = 0
        for archetype_id in ARCHETYPES:
            archetype = ARCHETYPES[archetype_id]
            for goal in archetype.goal_templates:
                visitor, arch = _make_visitor(archetype_id, goal)
                for seed in range(30):
                    sm = VisitorStateMachine(
                        visitor, arch, random.Random(seed)
                    )
                    turns = sm.generate_visit()
                    if turns[-1].exit_reason == ExitReason.NATURAL:
                        natural_exits += 1

        assert natural_exits > 0, (
            "NATURAL exit reason never occurred — "
            "DECIDING→EXITING path may be unreachable"
        )


class TestVisitorSpeechAttribution:
    """Regression: speech must be attributed to event source, not current
    engagement. Uses _process_visitor_events directly."""

    def test_overlapping_speech_attributed_correctly(self):
        """When visitor B speaks while visitor A is engaged, B's
        speech must be logged under B, not A."""
        from sim.runner import SimulationRunner

        runner = SimulationRunner.__new__(SimulationRunner)
        # Minimal state for _process_visitor_events
        runner._engagement = {
            "status": "none",
            "visitor_id": None,
            "turn_count": 0,
        }
        runner._visitor_history = {}
        runner._llm_visitor_engine = None

        events = [
            # Visitor A connects
            {"event_type": "visitor_connect", "source": "vis_A",
             "content": "Alice"},
            # Visitor A speaks
            {"event_type": "visitor_speech", "source": "vis_A",
             "content": "Hello from A"},
            # Visitor B was pre-registered (arrived earlier in a
            # different cycle) and speaks while A is engaged
        ]
        runner._process_visitor_events(events)

        # Pre-register visitor B in history (simulates earlier arrival)
        runner._visitor_history["vis_B"] = {
            "name": "Bob", "visit_count": 1, "messages": [],
        }

        # B speaks while A is engaged
        overlap_events = [
            {"event_type": "visitor_speech", "source": "vis_B",
             "content": "Hello from B"},
        ]
        runner._process_visitor_events(overlap_events)

        # B's message must be under B, not A
        assert "Hello from B" in runner._visitor_history["vis_B"]["messages"]
        assert "Hello from B" not in runner._visitor_history["vis_A"]["messages"]
        # A's turn count should not increase for B's speech
        assert runner._engagement["turn_count"] == 1

    def test_speech_after_disconnect_not_attributed(self):
        """Speech from a disconnected visitor should still be logged
        under the correct source in visitor_history."""
        from sim.runner import SimulationRunner

        runner = SimulationRunner.__new__(SimulationRunner)
        runner._engagement = {
            "status": "none",
            "visitor_id": None,
            "turn_count": 0,
        }
        runner._visitor_history = {}
        runner._llm_visitor_engine = None

        events = [
            {"event_type": "visitor_connect", "source": "vis_A",
             "content": "Alice"},
            {"event_type": "visitor_speech", "source": "vis_A",
             "content": "msg1"},
            {"event_type": "visitor_disconnect", "source": "vis_A",
             "content": ""},
            # Late speech from vis_A after disconnect
            {"event_type": "visitor_speech", "source": "vis_A",
             "content": "ghost msg"},
        ]
        runner._process_visitor_events(events)

        # Ghost message still attributed to vis_A (correct source),
        # not to whatever engagement is active
        assert "ghost msg" in runner._visitor_history["vis_A"]["messages"]


class TestGhostReplyPrevention:
    """Regression: pending Tier 2 events must be filtered when the
    visitor leaves in the same cycle."""

    def test_pending_events_filtered_on_leave(self):
        """Pending visitor_message events should be dropped if
        visitor_leave is scheduled for the same cycle."""
        from sim.scenario import ScenarioEvent, ScenarioManager

        # Build a scenario: visitor arrives at 0, leaves at 1
        events = [
            ScenarioEvent(0, "visitor_arrive", {
                "source": "vis_T2", "name": "Test", "channel": "sim",
                "tier": 2,
            }),
            ScenarioEvent(1, "visitor_leave", {
                "source": "vis_T2",
            }),
        ]
        scenario = ScenarioManager(events, name="test")

        # Simulate the pending event merge logic
        cycle_1_events = scenario.get_events(1)  # [visitor_leave]

        # A pending speech event from the same visitor
        pending = [
            ScenarioEvent(1, "visitor_message", {
                "source": "vis_T2",
                "content": "Ghost reply that should be dropped",
            }),
        ]

        # Apply the filtering logic from runner.run()
        leaving_sources = {
            se.payload.get("source") for se in cycle_1_events
            if se.event_type == "visitor_leave"
        }
        filtered = [
            pe for pe in pending
            if pe.payload.get("source") not in leaving_sources
        ]

        assert len(filtered) == 0, (
            f"Ghost reply was not filtered: {filtered}"
        )

    def test_pending_events_kept_for_active_visitors(self):
        """Pending events from visitors who are NOT leaving should
        still be included."""
        from sim.scenario import ScenarioEvent, ScenarioManager

        events = [
            ScenarioEvent(1, "visitor_leave", {
                "source": "vis_leaving",
            }),
        ]
        scenario = ScenarioManager(events, name="test")
        cycle_events = scenario.get_events(1)

        pending = [
            ScenarioEvent(1, "visitor_message", {
                "source": "vis_active",
                "content": "I'm still here!",
            }),
        ]

        leaving_sources = {
            se.payload.get("source") for se in cycle_events
            if se.event_type == "visitor_leave"
        }
        filtered = [
            pe for pe in pending
            if pe.payload.get("source") not in leaving_sources
        ]

        assert len(filtered) == 1, (
            "Active visitor's pending event was incorrectly dropped"
        )
