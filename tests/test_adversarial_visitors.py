"""Tests for adversarial returning visitors (TASK-083).

Tests cover:
1. AdversarialScorer — scoring rules for all 3 conflict types
2. ReturningVisitorManager — adversarial scheduling + doppelgangers
3. Adversarial dialogue template generation
4. Report export
"""

from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path

import pytest

from sim.metrics.memory_score import AdversarialEpisode, AdversarialScorer
from sim.reports.adversarial import export_adversarial_report
from sim.visitors.models import (
    DayPart,
    ScheduledArrival,
    VisitSummary,
    VisitorInstance,
    VisitorTier,
    VisitorTraits,
)
from sim.visitors.returning import (
    AdversarialInfo,
    ReturningVisitorManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_arrival(
    visitor_id: str = "v001",
    name: str = "Tanaka-san",
    cycle: int = 50,
    duration: int = 6,
    goal: str = "buy",
    archetype_id: str = "regular_tanaka",
) -> ScheduledArrival:
    """Helper: create a ScheduledArrival for testing."""
    visitor = VisitorInstance(
        visitor_id=visitor_id,
        tier=VisitorTier.TIER_1,
        archetype_id=archetype_id,
        name=name,
        traits=VisitorTraits(patience=0.7, knowledge=0.5, budget=0.5),
        goal=goal,
    )
    return ScheduledArrival(
        cycle=cycle,
        visitor=visitor,
        day_part=DayPart.AFTERNOON,
        visit_duration_cycles=duration,
    )


# ===========================================================================
# AdversarialScorer — Scoring Rules
# ===========================================================================


class TestDoppelgangerScoring:
    """Tests for doppelganger conflict type scoring."""

    def test_pass_when_clarification_asked(self):
        """Doppelganger PASS: shopkeeper asked disambiguation question."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="doppel_v001",
            visit_id="visit_1",
            conflict_type="doppelganger",
            shopkeeper_dialogues=["Have we met before? I might be confused."],
            original_visitor_id="v001",
        )
        assert ep.outcome == "PASS"
        assert ep.asked_clarification is True

    def test_pass_when_not_recognized(self):
        """Doppelganger PASS: treated as new person (no false recognition)."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="doppel_v001",
            visit_id="visit_1",
            conflict_type="doppelganger",
            shopkeeper_dialogues=["Welcome to my shop. How can I help you today?"],
            original_visitor_id="v001",
        )
        assert ep.outcome == "PASS"
        assert ep.recognized is False
        assert "new person" in ep.reason

    def test_fail_when_wrong_recognition(self):
        """Doppelganger FAIL: recognized as wrong person without asking."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="doppel_v001",
            visit_id="visit_1",
            conflict_type="doppelganger",
            shopkeeper_dialogues=[
                "Welcome back! Last time you bought that vintage card.",
            ],
            original_visitor_id="v001",
        )
        assert ep.outcome == "FAIL"
        assert ep.recognized is True
        assert ep.asked_clarification is False


class TestPreferenceDriftScoring:
    """Tests for preference drift conflict type scoring."""

    def test_pass_when_memory_updated_and_recommendation_reflects(self):
        """Preference drift PASS: memory updated AND recommendation reflects new preference."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="v001",
            visit_id="visit_2",
            conflict_type="preference_drift",
            shopkeeper_dialogues=[
                "I see you've changed your interests!",
                "Let me show you some holographic cards we just got in.",
            ],
            memory_updates=[
                {"type": "trait_observation", "content": "Now prefers holographic cards"},
            ],
            old_preference="vintage cards",
            new_preference="holographic cards",
        )
        assert ep.outcome == "PASS"
        assert ep.updated_memory is True
        assert ep.recommendation_reflects_new is True
        assert "recommendation reflects" in ep.reason

    def test_pass_when_memory_updated_recommendation_unclear(self):
        """Preference drift PASS (partial): memory updated but dialogue doesn't reference new pref."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="v001",
            visit_id="visit_2",
            conflict_type="preference_drift",
            shopkeeper_dialogues=["I see you've changed your interests!"],
            memory_updates=[
                {"type": "trait_observation", "content": "Now prefers holographic cards"},
            ],
            old_preference="vintage cards",
            new_preference="holographic cards",
        )
        assert ep.outcome == "PASS"
        assert ep.updated_memory is True
        assert ep.recommendation_reflects_new is False
        assert "unclear" in ep.reason

    def test_pass_when_memory_updated_no_preference_data(self):
        """Preference drift PASS: memory updated, no preference data supplied (backward compat)."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="v001",
            visit_id="visit_2",
            conflict_type="preference_drift",
            shopkeeper_dialogues=["I see you've changed your interests!"],
            memory_updates=[
                {"type": "trait_observation", "content": "Now prefers holographic cards"},
            ],
        )
        assert ep.outcome == "PASS"
        assert ep.updated_memory is True

    def test_fail_when_no_memory_update(self):
        """Preference drift FAIL: ignored the preference change."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="v001",
            visit_id="visit_2",
            conflict_type="preference_drift",
            shopkeeper_dialogues=["Let me show you these vintage cards."],
            memory_updates=[],
            old_preference="vintage cards",
            new_preference="holographic cards",
        )
        assert ep.outcome == "FAIL"
        assert ep.updated_memory is False


class TestConflictScoring:
    """Tests for conflict dispute scoring."""

    def test_pass_with_uncertainty(self):
        """Conflict PASS: expressed uncertainty about disputed transaction."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="v001",
            visit_id="visit_2",
            conflict_type="conflict",
            shopkeeper_dialogues=["I'm not sure about that. Let me check my records."],
            monologue="Something feels off. Might be confused about this visitor.",
        )
        assert ep.outcome == "PASS"
        assert ep.marked_uncertainty is True

    def test_pass_with_clarification(self):
        """Conflict PASS: asked for clarification about the dispute."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="v001",
            visit_id="visit_2",
            conflict_type="conflict",
            shopkeeper_dialogues=["Could you remind me what happened exactly?"],
        )
        assert ep.outcome == "PASS"
        assert ep.asked_clarification is True

    def test_fail_blind_overwrite(self):
        """Conflict FAIL: blindly overwrote memory without uncertainty."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="v001",
            visit_id="visit_2",
            conflict_type="conflict",
            shopkeeper_dialogues=["Oh, I apologize! My mistake."],
            memory_updates=[
                {"type": "visitor_impression", "content": "They never bought a card"},
            ],
        )
        assert ep.outcome == "FAIL"
        assert ep.updated_memory is True
        assert ep.marked_uncertainty is False
        assert "blindly overwrote" in ep.reason

    def test_fail_no_response(self):
        """Conflict FAIL: neither clarified nor expressed uncertainty."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            visitor_id="v001",
            visit_id="visit_2",
            conflict_type="conflict",
            shopkeeper_dialogues=["Here are some cards you might like."],
        )
        assert ep.outcome == "FAIL"


# ===========================================================================
# AdversarialScorer — Aggregate Metrics
# ===========================================================================


class TestAggregateMetrics:
    """Tests for aggregate adversarial metrics computation."""

    def test_empty_scorer(self):
        """No episodes → all rates 0."""
        scorer = AdversarialScorer()
        metrics = scorer.compute_metrics()
        assert metrics["total_episodes"] == 0
        assert metrics["adversarial_overall_pass_rate"] == 0.0

    def test_mixed_outcomes(self):
        """Mixed pass/fail across types → correct per-type and overall rates."""
        scorer = AdversarialScorer()

        # 2 doppelganger episodes: 1 pass, 1 fail
        scorer.evaluate_episode("d1", "v1", "doppelganger",
                                ["Welcome to the shop."])  # PASS (not recognized)
        scorer.evaluate_episode("d2", "v2", "doppelganger",
                                ["Welcome back! You were here last time."])  # FAIL

        # 1 preference_drift: pass
        scorer.evaluate_episode("p1", "v3", "preference_drift",
                                ["New taste!"],
                                memory_updates=[{"type": "trait_observation", "content": "x"}])

        # 1 conflict: pass
        scorer.evaluate_episode("c1", "v4", "conflict",
                                ["I'm not sure about that."])

        metrics = scorer.compute_metrics()
        assert metrics["total_episodes"] == 4
        assert metrics["doppelganger_pass_rate"] == 0.5
        assert metrics["preference_drift_pass_rate"] == 1.0
        assert metrics["conflict_pass_rate"] == 1.0
        assert metrics["adversarial_overall_pass_rate"] == 0.75


# ===========================================================================
# ReturningVisitorManager — Adversarial Scheduling
# ===========================================================================


class TestAdversarialScheduling:
    """Tests for adversarial flag assignment on return visitors."""

    def test_returns_get_adversarial_flags(self):
        """Some fraction of returns should get adversarial flags."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"Visitor-{i}", cycle=i * 20, duration=5)
            for i in range(20)
        ]
        returns = mgr.schedule_returns(arrivals, num_cycles=2000)

        # Should have some adversarial flags
        adv = mgr.adversarial_visitors
        assert len(adv) > 0, "Expected at least one adversarial flag"

        # Check types are valid
        for info in adv.values():
            assert info.adversarial_type in (
                "doppelganger", "preference_drift", "conflict",
            )

    def test_preference_drift_has_preferences(self):
        """Preference drift flags should have old/new preferences set."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"Visitor-{i}", cycle=i * 20, duration=5)
            for i in range(30)
        ]
        mgr.schedule_returns(arrivals, num_cycles=3000)

        drift_flags = [
            info for info in mgr.adversarial_visitors.values()
            if info.adversarial_type == "preference_drift"
        ]
        for info in drift_flags:
            assert info.old_preference, "old_preference should be set"
            assert info.new_preference, "new_preference should be set"
            assert info.old_preference != info.new_preference

    def test_conflict_has_transaction_detail(self):
        """Conflict flags should have transaction_detail set."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"Visitor-{i}", cycle=i * 20, duration=5)
            for i in range(30)
        ]
        mgr.schedule_returns(arrivals, num_cycles=3000)

        conflict_flags = [
            info for info in mgr.adversarial_visitors.values()
            if info.adversarial_type == "conflict"
        ]
        for info in conflict_flags:
            assert info.transaction_detail, "transaction_detail should be set"


class TestDoppelgangerScheduling:
    """Tests for doppelganger visitor creation."""

    def test_doppelgangers_created(self):
        """Doppelgangers should appear in adversarial arrivals."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"Visitor-{i}", cycle=i * 20, duration=5)
            for i in range(20)
        ]
        returns = mgr.schedule_returns(arrivals, num_cycles=3000)
        adversarial = mgr.schedule_adversarial(returns, num_cycles=3000)

        doppelgangers = [
            a for a in adversarial
            if a.visitor.archetype_id == "adversarial_doppelganger"
        ]
        assert len(doppelgangers) > 0, "Expected at least one doppelganger"

    def test_doppelganger_has_same_name(self):
        """Doppelganger shares the name of the original visitor."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"Visitor-{i}", cycle=i * 20, duration=5)
            for i in range(20)
        ]
        returns = mgr.schedule_returns(arrivals, num_cycles=3000)
        adversarial = mgr.schedule_adversarial(returns, num_cycles=3000)

        for arrival in adversarial:
            adv = mgr.get_adversarial_info(arrival.visitor.visitor_id)
            if adv and adv.adversarial_type == "doppelganger":
                # Doppelganger's name should match the original
                orig_id = adv.original_visitor_id
                # Find original among initial arrivals
                orig_arrival = next(
                    (a for a in arrivals if a.visitor.visitor_id == orig_id),
                    None,
                )
                if orig_arrival:
                    assert arrival.visitor.name == orig_arrival.visitor.name

    def test_doppelganger_has_different_id(self):
        """Doppelganger has a different visitor_id from the original."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"Visitor-{i}", cycle=i * 20, duration=5)
            for i in range(20)
        ]
        returns = mgr.schedule_returns(arrivals, num_cycles=3000)
        adversarial = mgr.schedule_adversarial(returns, num_cycles=3000)

        for arrival in adversarial:
            adv = mgr.get_adversarial_info(arrival.visitor.visitor_id)
            if adv and adv.adversarial_type == "doppelganger":
                assert arrival.visitor.visitor_id != adv.original_visitor_id

    def test_doppelganger_max_count(self):
        """No more than 3 doppelgangers per run."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"Visitor-{i}", cycle=i * 20, duration=5)
            for i in range(50)
        ]
        returns = mgr.schedule_returns(arrivals, num_cycles=5000)
        adversarial = mgr.schedule_adversarial(returns, num_cycles=5000)

        doppelgangers = [
            a for a in adversarial
            if a.visitor.archetype_id == "adversarial_doppelganger"
        ]
        assert len(doppelgangers) <= 3


# ===========================================================================
# Adversarial Entering Text
# ===========================================================================


class TestAdversarialDialogue:
    """Tests for adversarial-specific entering dialogue."""

    def test_doppelganger_entering_text(self):
        """Doppelganger entering text should NOT reference prior visits."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"Visitor-{i}", cycle=i * 20, duration=6)
            for i in range(10)
        ]
        returns = mgr.schedule_returns(arrivals, num_cycles=2000)
        adversarial = mgr.schedule_adversarial(returns, num_cycles=2000)

        rng = random.Random(99)
        found = False
        for arrival in adversarial:
            adv = mgr.get_adversarial_info(arrival.visitor.visitor_id)
            if adv and adv.adversarial_type == "doppelganger":
                text = mgr.get_return_entering_text(arrival.visitor, rng)
                # Should not reference "back" or "again" (they're new)
                assert "I'm back" not in text
                assert "last time" not in text.lower()
                found = True
                break
        assert found, "Expected at least one doppelganger for dialogue test"

    def test_preference_drift_entering_text(self):
        """Preference drift text should mention old and new preferences."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"V-{i}", cycle=i * 20, duration=5)
            for i in range(30)
        ]
        returns = mgr.schedule_returns(arrivals, num_cycles=3000)

        rng = random.Random(99)
        for arrival in returns:
            adv = mgr.get_adversarial_info(arrival.visitor.visitor_id)
            if adv and adv.adversarial_type == "preference_drift":
                text = mgr.get_return_entering_text(arrival.visitor, rng)
                assert adv.old_preference in text
                assert adv.new_preference in text
                break

    def test_conflict_entering_text(self):
        """Conflict text should mention the disputed transaction."""
        mgr = ReturningVisitorManager(return_rate=1.0, seed=42)
        arrivals = [
            _make_arrival(f"v{i:03d}", f"V-{i}", cycle=i * 20, duration=5)
            for i in range(30)
        ]
        returns = mgr.schedule_returns(arrivals, num_cycles=3000)

        rng = random.Random(99)
        for arrival in returns:
            adv = mgr.get_adversarial_info(arrival.visitor.visitor_id)
            if adv and adv.adversarial_type == "conflict":
                text = mgr.get_return_entering_text(arrival.visitor, rng)
                assert adv.transaction_detail in text
                break


# ===========================================================================
# Report Export
# ===========================================================================


class TestReportExport:
    """Tests for adversarial_episodes.json export."""

    def test_export_creates_file(self):
        """Export creates adversarial_episodes.json."""
        scorer = AdversarialScorer()
        scorer.evaluate_episode("d1", "v1", "doppelganger",
                                ["Welcome to the shop."])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_adversarial_report(scorer, tmpdir)
            assert path.exists()
            assert path.name == "adversarial_episodes.json"

    def test_export_contains_episodes(self):
        """Exported JSON contains episode details and summary."""
        scorer = AdversarialScorer()
        scorer.evaluate_episode("d1", "v1", "doppelganger",
                                ["Welcome to the shop."])
        scorer.evaluate_episode("p1", "v2", "preference_drift",
                                ["New taste!"],
                                memory_updates=[{"type": "trait_observation", "content": "x"}])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_adversarial_report(scorer, tmpdir)
            data = json.loads(path.read_text())

            assert "summary" in data
            assert "episodes" in data
            assert len(data["episodes"]) == 2
            assert data["summary"]["total_episodes"] == 2

    def test_export_episode_fields(self):
        """Each exported episode has all required fields."""
        scorer = AdversarialScorer()
        scorer.evaluate_episode("d1", "v1", "doppelganger",
                                ["Hello."], original_visitor_id="orig_1")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_adversarial_report(scorer, tmpdir)
            data = json.loads(path.read_text())
            ep = data["episodes"][0]

            expected_fields = {
                "visitor_id", "visit_id", "conflict_type",
                "original_visitor_id", "old_preference", "new_preference",
                "recommendation_reflects_new", "recognized",
                "asked_clarification", "updated_memory",
                "marked_uncertainty", "outcome", "reason",
            }
            assert set(ep.keys()) == expected_fields


# ===========================================================================
# Detection Heuristics
# ===========================================================================


class TestDetectionHeuristics:
    """Tests for signal detection in shopkeeper output."""

    def test_recognize_via_recognition_phrase(self):
        """Recognition phrases trigger recognized=True."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "d1", "v1", "doppelganger",
            ["Welcome back! Good to see you again."],
        )
        assert ep.recognized is True

    def test_recognize_via_transaction_phrase(self):
        """Transaction phrases trigger recognized=True."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "d1", "v1", "doppelganger",
            ["Last time you bought a rare card from me."],
        )
        assert ep.recognized is True

    def test_clarification_via_question(self):
        """Question about identity triggers asked_clarification=True."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "d1", "v1", "doppelganger",
            ["Have you been here before?"],
        )
        assert ep.asked_clarification is True

    def test_uncertainty_in_monologue(self):
        """Uncertainty language in monologue triggers marked_uncertainty."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "c1", "v1", "conflict",
            ["Let me check that for you."],
            monologue="I'm not sure this is the same person. Something feels off.",
        )
        assert ep.marked_uncertainty is True

    def test_uncertainty_in_memory_update(self):
        """Uncertainty language in memory updates triggers marked_uncertainty."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "c1", "v1", "conflict",
            ["I'll look into that."],
            memory_updates=[{"type": "visitor_impression",
                             "content": "Might be confused about prior visit"}],
        )
        assert ep.marked_uncertainty is True

    def test_memory_update_detected(self):
        """Memory updates with relevant types trigger updated_memory."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "p1", "v1", "preference_drift",
            ["Interesting!"],
            memory_updates=[{"type": "trait_observation", "content": "likes holo"}],
        )
        assert ep.updated_memory is True

    def test_no_false_recognition(self):
        """Neutral dialogue should not trigger recognition."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "d1", "v1", "doppelganger",
            ["Good afternoon. How can I help you today?"],
        )
        assert ep.recognized is False
        assert ep.asked_clarification is False

    def test_recommendation_reflects_new_preference(self):
        """Recommendation detection finds new preference in dialogue."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "p1", "v1", "preference_drift",
            ["I have some great holographic cards you might like!"],
            memory_updates=[{"type": "trait_observation", "content": "prefers holo"}],
            old_preference="vintage cards",
            new_preference="holographic cards",
        )
        assert ep.recommendation_reflects_new is True

    def test_recommendation_does_not_match_old_preference(self):
        """Recommendation detection returns False when dialogue only references old preference."""
        scorer = AdversarialScorer()
        ep = scorer.evaluate_episode(
            "p1", "v1", "preference_drift",
            ["Let me show you our vintage cards collection."],
            memory_updates=[{"type": "trait_observation", "content": "updated pref"}],
            old_preference="vintage cards",
            new_preference="holographic cards",
        )
        assert ep.recommendation_reflects_new is False
