"""Tests for sim.reports.comparison — Cross-scenario comparison report."""

import json
import tempfile
from pathlib import Path

import pytest
from sim.reports.comparison import (
    ScenarioComparison,
    _CycleAdapter,
    _social_hunger_saturation_streak,
)


def _make_cycles(actions: list[str], monologues: list[str] | None = None) -> list[dict]:
    """Helper to build cycle dicts from action lists."""
    cycles = []
    for i, action in enumerate(actions):
        ctype = "idle"
        if action == "speak":
            ctype = "dialogue"
        elif action in ("read_content", "browse_web"):
            ctype = "browse"
        elif action == "write_journal":
            ctype = "journal"
        elif action in ("post_x", "reply_x"):
            ctype = "post"
        elif action == "sleep":
            ctype = "sleep"
            action = None

        mono = monologues[i] if monologues and i < len(monologues) else f"Thought {i}"

        cycle_dict: dict = {
            "cycle": i,
            "type": ctype,
            "action": action,
            "has_visitor": ctype == "dialogue",
            "dialogue": "Hello" if ctype == "dialogue" else None,
            "monologue": mono,
            "drives": {"mood_valence": 0.1 * (i % 5 - 2), "mood_arousal": 0.3,
                        "social_hunger": 0.5},
            "budget_spent_usd": 0.01 * (i + 1),
            "budget_usd_daily_cap": 1.0,
            "budget_remaining_usd": 1.0 - 0.01 * (i + 1),
            "memory_updates": [],
            "intentions": [],
            "resonance": False,
        }
        if ctype == "sleep":
            cycle_dict["budget_after_sleep_usd"] = 1.0
        cycles.append(cycle_dict)
    return cycles


def _make_result(scenario: str, actions: list[str], **kwargs) -> dict:
    """Build a minimal result dict."""
    cycles = _make_cycles(actions)
    return {
        "scenario": scenario,
        "variant": kwargs.get("variant", "full"),
        "seed": kwargs.get("seed", 42),
        "num_cycles": len(cycles),
        "cycles": cycles,
        "total_posts": sum(1 for a in actions if a in ("post_x", "reply_x")),
        "total_journals": sum(1 for a in actions if a == "write_journal"),
        **kwargs,
    }


class TestScenarioComparison:
    """Test cross-scenario comparison."""

    def test_single_scenario(self):
        result = _make_result("standard", ["speak", "read_content", "rearrange", None])
        comp = ScenarioComparison({"standard": result})
        table = comp.comparison_table()
        assert len(table) == 1
        assert table[0]["scenario"] == "standard"

    def test_multiple_scenarios(self):
        isolation = _make_result("isolation", [None, None, None, "rearrange"])
        standard = _make_result("standard", ["speak", "read_content", None, "rearrange"])
        comp = ScenarioComparison({"isolation": isolation, "standard": standard})
        table = comp.comparison_table()
        assert len(table) == 2

    def test_n2_metrics_present(self):
        result = _make_result("standard", ["speak", "read_content", "rearrange"])
        comp = ScenarioComparison({"standard": result})
        table = comp.comparison_table()
        row = table[0]
        assert "n2_max_streak" in row
        assert "n2_self_loop" in row
        assert "n2_passed" in row

    def test_n4_metrics_present(self):
        result = _make_result("standard", ["speak", "read_content", "rearrange"])
        comp = ScenarioComparison({"standard": result})
        table = comp.comparison_table()
        row = table[0]
        assert "n4_efficiency" in row
        assert "n4_meaningful_pct" in row


class TestN1CrossScenario:
    """Test N1 stimulus-response coupling across scenarios."""

    def test_compute_n1(self):
        isolation = _make_result("isolation", [None, None, None, "rearrange"] * 5)
        stress = _make_result("stress", ["speak", "speak", "read_content", None] * 5)
        comp = ScenarioComparison({"isolation": isolation, "stress": stress})
        n1 = comp.compute_n1("isolation", "stress")
        assert n1 is not None
        assert n1.dialogue_delta > 0

    def test_compute_n1_missing_scenario(self):
        result = _make_result("standard", ["speak"])
        comp = ScenarioComparison({"standard": result})
        n1 = comp.compute_n1("standard", "nonexistent")
        assert n1 is None


class TestInvariantCheck:
    """Test CI invariant assertions."""

    def test_good_run_invariants(self):
        actions = [
            "speak", "read_content", "rearrange", "write_journal",
            "express_thought", "post_x", "browse_web", "speak",
            None, "reply_x",
        ]
        result = _make_result("standard", actions, total_posts=2, total_journals=1)
        comp = ScenarioComparison({"standard": result})
        checks = comp.invariant_check()
        std_checks = checks["standard"]
        assert std_checks["self_loop_lt_0.7"] is True
        assert std_checks["max_streak_lt_20"] is True
        assert std_checks["repetition_lt_0.7"] is True
        assert std_checks["social_hunger_streak_lt_50"] is True
        assert std_checks["posts_or_journals_gt_0"] is True

    def test_bad_run_invariants(self):
        actions = ["rearrange"] * 25
        result = _make_result("standard", actions, total_posts=0, total_journals=0)
        comp = ScenarioComparison({"standard": result})
        checks = comp.invariant_check()
        std_checks = checks["standard"]
        assert std_checks["max_streak_lt_20"] is False
        assert std_checks["posts_or_journals_gt_0"] is False

    def test_standard_only_invariants_not_in_other_scenarios(self):
        """Invariants 1, 3, 4 should only appear for 'standard' scenario."""
        actions = ["rearrange"] * 10
        isolation = _make_result("isolation", actions)
        comp = ScenarioComparison({"isolation": isolation})
        checks = comp.invariant_check()
        iso_checks = checks["isolation"]
        # Standard-only invariants should not be present
        assert "self_loop_lt_0.7" not in iso_checks
        assert "repetition_lt_0.7" not in iso_checks
        assert "social_hunger_streak_lt_50" not in iso_checks
        # Universal invariants should be present
        assert "max_streak_lt_20" in iso_checks
        assert "unique_actions_gte_8" in iso_checks
        assert "posts_or_journals_gt_0" in iso_checks

    def test_social_hunger_saturation_streak_fails(self):
        """Invariant 4 fails when social_hunger is saturated for 50+ cycles."""
        # Build cycles with social_hunger at 0.99 for 60 consecutive cycles
        cycles = []
        for i in range(60):
            cycles.append({
                "cycle": i,
                "type": "idle",
                "action": None,
                "drives": {"social_hunger": 0.99},
                "budget_spent_usd": 0.0,
                "budget_usd_daily_cap": 1.0,
                "budget_remaining_usd": 1.0,
                "memory_updates": [],
            })
        result = {
            "scenario": "standard",
            "variant": "full",
            "seed": 42,
            "num_cycles": 60,
            "cycles": cycles,
            "total_posts": 0,
            "total_journals": 0,
        }
        comp = ScenarioComparison({"standard": result})
        checks = comp.invariant_check()
        assert checks["standard"]["social_hunger_streak_lt_50"] is False


class TestExport:
    """Test CSV and JSON export."""

    def test_export_csv(self):
        result = _make_result("standard", ["speak", "read_content", None])
        comp = ScenarioComparison({"standard": result})
        with tempfile.TemporaryDirectory() as tmpdir:
            comp.export_csv(tmpdir)
            csv_path = Path(tmpdir) / "scenario_comparison.csv"
            assert csv_path.exists()
            content = csv_path.read_text()
            assert "scenario" in content
            assert "standard" in content

    def test_export_json(self):
        isolation = _make_result("isolation", [None, None, "rearrange"])
        standard = _make_result("standard", ["speak", "read_content"])
        comp = ScenarioComparison({"isolation": isolation, "standard": standard})
        with tempfile.TemporaryDirectory() as tmpdir:
            comp.export_json(tmpdir)
            json_path = Path(tmpdir) / "scenario_comparison.json"
            assert json_path.exists()
            data = json.loads(json_path.read_text())
            assert "comparison" in data
            assert "n1_stimulus_response" in data
            assert "invariants" in data


class TestCycleAdapter:
    """Test the adapter that wraps cycle dicts for SimMetricsCollector."""

    def test_properties(self):
        c = _CycleAdapter({
            "type": "dialogue",
            "action": "speak",
            "has_visitor": True,
            "dialogue": "Hello",
            "drives": {"mood_valence": 0.5},
            "resonance": True,
        })
        assert c.cycle_type == "dialogue"
        assert c.action == "speak"
        assert c.has_visitor is True
        assert c.dialogue == "Hello"
        assert c.drives == {"mood_valence": 0.5}
        assert c.resonance is True

    def test_defaults(self):
        c = _CycleAdapter({})
        assert c.cycle_type == "idle"
        assert c.action is None
        assert c.has_visitor is False
        assert c.dialogue is None
        assert c.drives == {}
        assert c.resonance is False

    def test_sleep_triggered(self):
        c = _CycleAdapter({"type": "sleep"})
        assert c.sleep_triggered is True
        c2 = _CycleAdapter({"type": "idle"})
        assert c2.sleep_triggered is False

    def test_budget_fields(self):
        c = _CycleAdapter({
            "budget_usd_daily_cap": 2.0,
            "budget_remaining_usd": 1.5,
            "budget_after_sleep_usd": 2.0,
        })
        assert c.budget_usd_daily_cap == 2.0
        assert c.budget_remaining_usd == 1.5
        assert c.budget_after_sleep_usd == 2.0

    def test_budget_defaults(self):
        c = _CycleAdapter({})
        assert c.budget_usd_daily_cap == 1.0
        assert c.budget_remaining_usd == 1.0
        assert c.budget_after_sleep_usd is None


class TestSocialHungerStreak:
    """Test _social_hunger_saturation_streak helper."""

    def test_empty(self):
        assert _social_hunger_saturation_streak([]) == 0

    def test_no_saturation(self):
        cycles = [{"drives": {"social_hunger": 0.5}} for _ in range(10)]
        assert _social_hunger_saturation_streak(cycles) == 0

    def test_full_saturation(self):
        cycles = [{"drives": {"social_hunger": 0.99}} for _ in range(10)]
        assert _social_hunger_saturation_streak(cycles) == 10

    def test_broken_streak(self):
        cycles = (
            [{"drives": {"social_hunger": 0.99}}] * 5
            + [{"drives": {"social_hunger": 0.3}}]
            + [{"drives": {"social_hunger": 0.99}}] * 3
        )
        assert _social_hunger_saturation_streak(cycles) == 5

    def test_threshold_boundary(self):
        """0.95 is the threshold — exactly 0.95 counts as saturated."""
        cycles = [{"drives": {"social_hunger": 0.95}}] * 10
        assert _social_hunger_saturation_streak(cycles) == 10
        cycles_below = [{"drives": {"social_hunger": 0.949}}] * 10
        assert _social_hunger_saturation_streak(cycles_below) == 0
