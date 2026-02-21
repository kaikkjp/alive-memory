"""Tests for sim.reports.comparison — Cross-scenario comparison report."""

import json
import tempfile
from pathlib import Path

import pytest
from sim.reports.comparison import ScenarioComparison, _CycleAdapter


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

        cycles.append({
            "cycle": i,
            "type": ctype,
            "action": action,
            "has_visitor": ctype == "dialogue",
            "dialogue": "Hello" if ctype == "dialogue" else None,
            "monologue": mono,
            "drives": {"mood_valence": 0.1 * (i % 5 - 2), "mood_arousal": 0.3},
            "budget_spent_usd": 0.01 * (i + 1),
            "budget_remaining_usd": 1.0 - 0.01 * (i + 1),
            "memory_updates": [],
            "intentions": [],
            "resonance": False,
        })
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
        assert std_checks["posts_or_journals_gt_0"] is True

    def test_bad_run_invariants(self):
        actions = ["rearrange"] * 25
        result = _make_result("standard", actions, total_posts=0, total_journals=0)
        comp = ScenarioComparison({"standard": result})
        checks = comp.invariant_check()
        std_checks = checks["standard"]
        assert std_checks["max_streak_lt_20"] is False
        assert std_checks["posts_or_journals_gt_0"] is False


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
