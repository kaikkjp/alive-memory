"""Tests for sim.metrics — Collector, Comparator, and Exporter."""

import json
import pytest
from pathlib import Path
from dataclasses import dataclass, field

from sim.metrics.collector import SimMetricsCollector
from sim.metrics.comparator import MetricsComparator
from sim.metrics.exporter import FigureExporter


@dataclass
class FakeCycleResult:
    """Minimal cycle result for testing metrics."""
    cycle_num: int
    cycle_type: str = "idle"
    action: str | None = None
    dialogue: str | None = None
    has_visitor: bool = False
    drives: dict = field(default_factory=lambda: {
        "mood_valence": 0.0, "energy": 0.8,
    })
    intentions: list = field(default_factory=list)
    memory_updates: list = field(default_factory=list)
    resonance: bool = False
    sleep_triggered: bool = False
    internal_monologue: str = ""


class TestCollector:
    def test_m1_uptime(self):
        c = SimMetricsCollector()
        for i in range(100):
            c.record_cycle(i, FakeCycleResult(cycle_num=i))
        metrics = c.compute_all()
        assert metrics["m1_uptime"] == 100

    def test_m2_initiative_rate(self):
        c = SimMetricsCollector()
        # 5 cycles with actions, 5 without (no visitor)
        for i in range(10):
            if i < 5:
                c.record_cycle(i, FakeCycleResult(
                    cycle_num=i, action="read_content", cycle_type="browse",
                ))
            else:
                c.record_cycle(i, FakeCycleResult(cycle_num=i))
        metrics = c.compute_all()
        assert metrics["m2_initiative_rate"] == 50.0

    def test_m3_entropy(self):
        c = SimMetricsCollector()
        # Uniform distribution across 4 actions
        actions = ["read_content", "write_journal", "post_x", "idle"]
        for i, action in enumerate(actions * 25):
            c.record_cycle(i, FakeCycleResult(
                cycle_num=i, action=action, cycle_type="browse",
            ))
        metrics = c.compute_all()
        # 4 equally distributed actions → entropy = 2.0
        assert abs(metrics["m3_entropy"] - 2.0) < 0.01

    def test_m3_entropy_single_action(self):
        c = SimMetricsCollector()
        for i in range(10):
            c.record_cycle(i, FakeCycleResult(
                cycle_num=i, action="idle", cycle_type="idle",
            ))
        metrics = c.compute_all()
        assert metrics["m3_entropy"] == 0.0

    def test_m4_knowledge(self):
        c = SimMetricsCollector()
        for i in range(5):
            c.record_cycle(i, FakeCycleResult(
                cycle_num=i,
                action="read_content",
                cycle_type="browse",
                intentions=[{"action": "read_content", "content": f"topic_{i}"}],
            ))
        metrics = c.compute_all()
        assert metrics["m4_knowledge"] == 5

    def test_m5_recall(self):
        c = SimMetricsCollector()
        for i in range(10):
            c.record_cycle(i, FakeCycleResult(
                cycle_num=i,
                cycle_type="dialogue",
                dialogue="Hello" if i % 2 == 0 else "...",
                has_visitor=True,
            ))
        metrics = c.compute_all()
        # 5 out of 10 are substantive (not "...")
        assert metrics["m5_recall"] == 50.0

    def test_m7_emotional_range(self):
        c = SimMetricsCollector()
        valences = [-0.5, -0.3, 0.0, 0.2, 0.5]
        for i, v in enumerate(valences):
            c.record_cycle(i, FakeCycleResult(
                cycle_num=i,
                drives={"mood_valence": v, "energy": 0.8},
            ))
        metrics = c.compute_all()
        assert abs(metrics["m7_emotional_range"] - 1.0) < 0.01

    def test_m9_unprompted_memories(self):
        c = SimMetricsCollector()
        for i in range(5):
            c.record_cycle(i, FakeCycleResult(
                cycle_num=i,
                memory_updates=[{"type": "observation", "content": "something"}],
            ))
        metrics = c.compute_all()
        assert metrics["m9_unprompted_memories"] == 5

    def test_m10_depth_gradient(self):
        c = SimMetricsCollector()
        # Early short dialogues, later long dialogues
        for i in range(20):
            if i < 10:
                dialogue = "Hi"  # short
            else:
                dialogue = "I've been thinking about this a lot and here's what I found"
            c.record_cycle(i, FakeCycleResult(
                cycle_num=i,
                cycle_type="dialogue",
                dialogue=dialogue,
                has_visitor=True,
            ))
        metrics = c.compute_all()
        # Q4 dialogues should be longer than Q1
        assert metrics["m10_depth_gradient"] > 1.0

    def test_empty_collector(self):
        c = SimMetricsCollector()
        metrics = c.compute_all()
        assert metrics["m1_uptime"] == 0
        assert metrics["m2_initiative_rate"] == 0.0
        assert metrics["m3_entropy"] == 0.0


class TestComparator:
    def test_comparison_table(self):
        results = {
            "full": {
                "m1_uptime": 100,
                "m2_initiative_rate": 45.0,
                "m3_entropy": 1.5,
                "m4_knowledge": 10,
                "m5_recall": 80.0,
                "m6_taste": 0.8,
                "m7_emotional_range": 1.2,
                "m9_unprompted_memories": 15,
                "m10_depth_gradient": 1.3,
            },
            "stateless": {
                "m1_uptime": 100,
                "m2_initiative_rate": 0.0,
                "m3_entropy": 0.5,
                "m4_knowledge": 0,
                "m5_recall": 60.0,
                "m6_taste": 0.2,
                "m7_emotional_range": 0.0,
                "m9_unprompted_memories": 0,
                "m10_depth_gradient": 1.0,
            },
        }
        comp = MetricsComparator(results)
        table = comp.comparison_table()
        assert len(table) == 2
        assert table[0]["System"] == "full"
        assert table[1]["System"] == "stateless"

    def test_ablation_table_with_full(self):
        results = {
            "full": {
                "m1_uptime": 100,
                "m2_initiative_rate": 45.0,
                "m3_entropy": 1.5,
                "m7_emotional_range": 1.2,
                "m9_unprompted_memories": 15,
            },
            "no_drives": {
                "m1_uptime": 100,
                "m2_initiative_rate": 30.0,
                "m3_entropy": 1.0,
                "m7_emotional_range": 0.5,
                "m9_unprompted_memories": 10,
            },
        }
        comp = MetricsComparator(results)
        table = comp.ablation_table()
        assert len(table) == 2

        no_drives_row = [r for r in table if r["Variant"] == "no_drives"][0]
        assert no_drives_row["Initiative (%) (delta)"] == -15.0

    def test_export_csv(self, tmp_path):
        results = {
            "full": {"m2_initiative_rate": 45, "m3_entropy": 1.5,
                     "m4_knowledge": 10, "m5_recall": 80,
                     "m6_taste": 0.8, "m7_emotional_range": 1.2,
                     "m9_unprompted_memories": 15, "m10_depth_gradient": 1.3},
        }
        comp = MetricsComparator(results)
        comp.export_csv(str(tmp_path))
        assert (tmp_path / "table1_baselines.csv").exists()

    def test_export_json(self, tmp_path):
        results = {"full": {"m2_initiative_rate": 45}}
        comp = MetricsComparator(results)
        comp.export_json(str(tmp_path))
        assert (tmp_path / "metrics_comparison.json").exists()
        data = json.loads((tmp_path / "metrics_comparison.json").read_text())
        assert "comparison" in data


class TestExporter:
    def test_longitudinal_curves(self, tmp_path):
        result = {
            "drives_history": [
                {"cycle": i, "mood_valence": 0.1 * i, "mood_arousal": 0.3,
                 "energy": 0.8, "social_hunger": 0.5, "curiosity": 0.5,
                 "expression_need": 0.3}
                for i in range(100)
            ],
            "cycles": [
                {"type": "idle" if i % 3 != 0 else "browse"} for i in range(100)
            ],
        }
        FigureExporter.longitudinal_curves(result, str(tmp_path))
        assert (tmp_path / "fig1_drives_timeline.csv").exists()
        assert (tmp_path / "fig1_action_distribution.csv").exists()

    def test_death_spiral(self, tmp_path):
        result = {
            "drives_history": [
                {"cycle": i, "mood_valence": -0.5 + 0.01 * i}
                for i in range(50)
            ],
        }
        FigureExporter.death_spiral(result, str(tmp_path))
        assert (tmp_path / "fig4_valence_timeline.csv").exists()

    def test_comparison_bar(self, tmp_path):
        metrics = {
            "full": {"m2_initiative_rate": 45, "m3_entropy": 1.5,
                     "m4_knowledge": 10, "m5_recall": 80,
                     "m6_taste": 0.8, "m7_emotional_range": 1.2},
            "stateless": {"m2_initiative_rate": 0, "m3_entropy": 0.5,
                          "m4_knowledge": 0, "m5_recall": 60,
                          "m6_taste": 0.2, "m7_emotional_range": 0},
        }
        FigureExporter.comparison_bar(metrics, str(tmp_path))
        assert (tmp_path / "comparison_metrics.csv").exists()

    def test_empty_data(self, tmp_path):
        FigureExporter.longitudinal_curves({}, str(tmp_path))
        # Should not crash with empty data
