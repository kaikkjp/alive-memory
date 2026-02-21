"""sim.reports.comparison — Cross-scenario comparison report.

Runs N1-N4 metrics across multiple scenario results and produces
a unified comparison table suitable for the research paper.

Usage:
    from sim.reports.comparison import ScenarioComparison
    comp = ScenarioComparison(results)
    table = comp.comparison_table()
    comp.export_csv("sim/results/")
    comp.print_summary()
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sim.metrics.collector import SimMetricsCollector
from sim.metrics.loop_resistance import LoopResistanceMetric, LoopResistanceResult
from sim.metrics.budget_efficiency import BudgetEfficiencyMetric, BudgetEfficiencyResult
from sim.metrics.stimulus_response import StimulusResponseMetric, StimulusResponseResult


@dataclass
class ScenarioReport:
    """Full metric report for a single scenario run."""
    scenario: str
    variant: str
    seed: int
    num_cycles: int

    # M-metrics (from SimMetricsCollector)
    m_metrics: dict = field(default_factory=dict)

    # N-metrics
    n2_loop: LoopResistanceResult | None = None
    n4_budget: BudgetEfficiencyResult | None = None

    def to_row(self) -> dict:
        """Flatten into a dict suitable for CSV/table output."""
        row: dict[str, Any] = {
            "scenario": self.scenario,
            "variant": self.variant,
            "seed": self.seed,
            "cycles": self.num_cycles,
        }

        # M-metrics
        for key in ("m1_uptime", "m2_initiative_rate", "m3_entropy",
                     "m4_knowledge", "m5_recall", "m6_taste",
                     "m7_emotional_range", "m8_sleep_quality",
                     "m9_unprompted_memories", "m10_depth_gradient"):
            row[key] = self.m_metrics.get(key, "N/A")

        # N2
        if self.n2_loop:
            row["n2_max_streak"] = self.n2_loop.max_streak
            row["n2_repetition"] = self.n2_loop.monologue_repetition
            row["n2_self_loop"] = self.n2_loop.bigram_self_loop
            row["n2_passed"] = self.n2_loop.passed
            row["n2_score"] = self.n2_loop.score

        # N4
        if self.n4_budget:
            row["n4_efficiency"] = self.n4_budget.overall_efficiency
            row["n4_meaningful_pct"] = self.n4_budget.overall_meaningful_pct
            row["n4_total_spent"] = self.n4_budget.total_budget_spent

        return row


class ScenarioComparison:
    """Cross-scenario comparison report generator.

    Takes a dict mapping scenario names to their exported result dicts
    (as produced by SimulationResult.to_dict()).
    """

    def __init__(self, results: dict[str, dict]):
        """
        Args:
            results: Mapping of scenario name -> result dict.
                     Each result dict should contain "cycles", "variant",
                     "seed", "num_cycles", etc.
        """
        self.results = results
        self._reports: dict[str, ScenarioReport] = {}

        for name, data in results.items():
            self._reports[name] = self._build_report(name, data)

    def _build_report(self, name: str, data: dict) -> ScenarioReport:
        """Build a full ScenarioReport from raw result data."""
        cycles = data.get("cycles", [])

        # Compute M-metrics via SimMetricsCollector
        collector = SimMetricsCollector()
        for c in cycles:
            collector.record_cycle(c.get("cycle", 0), _CycleAdapter(c))
        m_metrics = collector.compute_all()

        # Compute N2: loop resistance
        n2 = LoopResistanceMetric.compute(cycles)

        # Compute N4: budget efficiency
        n4 = BudgetEfficiencyMetric.compute(cycles)

        return ScenarioReport(
            scenario=data.get("scenario", name),
            variant=data.get("variant", "full"),
            seed=data.get("seed", 0),
            num_cycles=data.get("num_cycles", len(cycles)),
            m_metrics=m_metrics,
            n2_loop=n2,
            n4_budget=n4,
        )

    def compute_n1(
        self,
        low_scenario: str,
        high_scenario: str,
    ) -> StimulusResponseResult | None:
        """Compute N1 stimulus-response coupling between two scenarios.

        Args:
            low_scenario: Name of the low-visitor scenario (e.g. "standard").
            high_scenario: Name of the high-visitor scenario (e.g. "stress").

        Returns:
            StimulusResponseResult, or None if either scenario is missing.
        """
        if low_scenario not in self.results or high_scenario not in self.results:
            return None
        return StimulusResponseMetric.from_results(
            self.results[low_scenario],
            self.results[high_scenario],
        )

    def comparison_table(self) -> list[dict]:
        """Generate a comparison table with all metrics per scenario.

        Returns list of row dicts, one per scenario.
        """
        return [report.to_row() for report in self._reports.values()]

    def invariant_check(self) -> dict[str, dict[str, bool]]:
        """Check CI invariants from the spec for each scenario.

        Invariants:
            1. action_bigram_self_loop_rate < 0.7 in standard
            2. max_identical_action_streak < 20 in any scenario
            3. monologue_repetition_ratio < 0.7 in standard
            4. social_hunger_saturation_streak < 50 in standard
            5. unique_action_types >= 8
            6. total_posts + total_journals > 0

        Returns dict of scenario -> {invariant_name: passed}.
        """
        checks: dict[str, dict[str, bool]] = {}

        for name, report in self._reports.items():
            scenario_checks: dict[str, bool] = {}
            data = self.results[name]
            cycles = data.get("cycles", [])

            # Invariant 1: self-loop < 0.7 (standard only)
            if report.n2_loop:
                scenario_checks["self_loop_lt_0.7"] = (
                    report.n2_loop.bigram_self_loop < 0.7
                )

            # Invariant 2: max streak < 20
            if report.n2_loop:
                scenario_checks["max_streak_lt_20"] = (
                    report.n2_loop.max_streak < 20
                )

            # Invariant 3: repetition < 0.7 (standard only)
            if report.n2_loop:
                scenario_checks["repetition_lt_0.7"] = (
                    report.n2_loop.monologue_repetition < 0.7
                )

            # Invariant 5: unique action types >= 8
            actions = set()
            for c in cycles:
                a = c.get("action")
                if a:
                    actions.add(a)
            scenario_checks["unique_actions_gte_8"] = len(actions) >= 8

            # Invariant 6: posts + journals > 0
            total_posts = data.get("total_posts", 0)
            total_journals = data.get("total_journals", 0)
            scenario_checks["posts_or_journals_gt_0"] = (
                total_posts + total_journals > 0
            )

            checks[name] = scenario_checks

        return checks

    def export_csv(self, output_dir: str | Path):
        """Export comparison table as CSV."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        table = self.comparison_table()
        if not table:
            return

        filepath = path / "scenario_comparison.csv"
        fieldnames = list(table[0].keys())
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(table)

    def export_json(self, output_dir: str | Path):
        """Export full comparison as JSON."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        # N1 pairs
        n1_results = {}
        scenario_names = list(self.results.keys())
        for i, lo in enumerate(scenario_names):
            for hi in scenario_names[i + 1:]:
                result = self.compute_n1(lo, hi)
                if result:
                    key = f"{lo}_vs_{hi}"
                    n1_results[key] = {
                        "dialogue_delta": result.dialogue_delta,
                        "browse_delta": result.browse_delta,
                        "rearrange_delta": result.rearrange_delta,
                        "score": result.score,
                        "passed": result.passed,
                    }

        output = {
            "comparison": self.comparison_table(),
            "n1_stimulus_response": n1_results,
            "invariants": self.invariant_check(),
        }

        (path / "scenario_comparison.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False, default=str)
        )

    def print_summary(self):
        """Print a human-readable summary table to stdout."""
        table = self.comparison_table()
        if not table:
            print("[Comparison] No scenario results to compare.")
            return

        # Header
        cols = [
            ("scenario", 12),
            ("m3_entropy", 10),
            ("m7_emotional_range", 10),
            ("n2_max_streak", 8),
            ("n2_self_loop", 10),
            ("n2_passed", 7),
            ("n4_meaningful_pct", 10),
        ]
        header = "  ".join(f"{label:>{width}}" for label, width in cols)
        print(f"\n{header}")
        print("-" * len(header))

        for row in table:
            values = []
            for label, width in cols:
                val = row.get(label, "N/A")
                if isinstance(val, float):
                    values.append(f"{val:>{width}.3f}")
                elif isinstance(val, bool):
                    values.append(f"{'PASS' if val else 'FAIL':>{width}}")
                else:
                    values.append(f"{str(val):>{width}}")
            print("  ".join(values))


class _CycleAdapter:
    """Adapter to make a cycle dict behave like CycleResult for SimMetricsCollector."""

    def __init__(self, data: dict):
        self._data = data

    @property
    def cycle_type(self) -> str:
        return self._data.get("type") or self._data.get("cycle_type", "idle")

    @property
    def action(self) -> str | None:
        return self._data.get("action")

    @property
    def has_visitor(self) -> bool:
        return self._data.get("has_visitor", False)

    @property
    def dialogue(self) -> str | None:
        return self._data.get("dialogue")

    @property
    def drives(self) -> dict:
        return self._data.get("drives", {})

    @property
    def intentions(self) -> list:
        return self._data.get("intentions", [])

    @property
    def memory_updates(self) -> list:
        return self._data.get("memory_updates", [])

    @property
    def resonance(self) -> bool:
        return self._data.get("resonance", False)

    @property
    def sleep_triggered(self) -> bool:
        return self._data.get("type") == "sleep" or self._data.get("cycle_type") == "sleep"
