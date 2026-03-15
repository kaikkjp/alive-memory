"""Report generator — produces markdown reports and charts from benchmark results.

Reads JSON result files, aggregates across seeds, computes confidence intervals,
and generates publication-quality output.
"""

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AggregatedMetric:
    """A metric aggregated across multiple seeds."""

    mean: float
    ci_low: float  # 95% CI lower bound
    ci_high: float  # 95% CI upper bound
    values: list[float]
    n: int

    def __str__(self) -> str:
        if self.n == 1:
            return f"{self.mean:.3f}"
        margin = (self.ci_high - self.ci_low) / 2
        return f"{self.mean:.3f} ± {margin:.3f}"


def _aggregate(values: list[float]) -> AggregatedMetric:
    """Aggregate values with 95% CI using t-distribution approximation."""
    if not values:
        return AggregatedMetric(0, 0, 0, [], 0)

    n = len(values)
    mean = statistics.mean(values)

    if n == 1:
        return AggregatedMetric(mean, mean, mean, values, 1)

    stdev = statistics.stdev(values)
    # t-value for 95% CI with n-1 degrees of freedom (approximation)
    t_values = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45}
    t = t_values.get(n - 1, 2.0)
    margin = t * stdev / math.sqrt(n)

    return AggregatedMetric(
        mean=mean,
        ci_low=mean - margin,
        ci_high=mean + margin,
        values=values,
        n=n,
    )


class ReportGenerator:
    """Generates markdown reports and charts from benchmark results."""

    def __init__(self, results_dir: str):
        self.results_dir = Path(results_dir)
        self.results: dict[str, dict[str, list[dict]]] = {}  # stream → system → [results]
        self._load_results()

    def _load_results(self) -> None:
        """Load all JSON result files from the results directory."""
        for stream_dir in self.results_dir.iterdir():
            if not stream_dir.is_dir() or stream_dir.name in ("charts",):
                continue

            stream_name = stream_dir.name
            self.results[stream_name] = {}

            for result_file in sorted(stream_dir.glob("*.json")):
                try:
                    data = json.loads(result_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue

                system_id = data.get("system_id", result_file.stem.split("_seed")[0])
                self.results[stream_name].setdefault(system_id, []).append(data)

    def generate_markdown(self, output_path: str) -> None:
        """Generate full comparison report as Markdown."""
        lines = [
            "# alive-memory Benchmark Report",
            "",
            f"Generated from results in `{self.results_dir}`",
            "",
            "All values: mean ± 95% CI from multiple seeds.",
            "No OVERALL row — readers draw their own conclusions.",
            "",
        ]

        for stream_name, systems in sorted(self.results.items()):
            lines.append(f"## Stream: {stream_name}")
            lines.append("")

            # Summary table
            lines.extend(self._summary_table(systems))
            lines.append("")

            # Per-category breakdown
            lines.extend(self._category_breakdown(systems))
            lines.append("")

            # Ranking Quality (NDCG)
            lines.extend(self._ranking_quality_section(systems))
            lines.append("")

            # Reliability (Hallucination + Entity Confusion)
            lines.extend(self._reliability_section(systems))
            lines.append("")

            # Degradation data
            lines.extend(self._degradation_section(systems))
            lines.append("")

            # Efficiency (Resource + Consolidation ROI + Graceful Degradation)
            lines.extend(self._resource_section(systems))
            lines.append("")
            lines.extend(self._efficiency_section(systems))
            lines.append("")

            # alive-memory Specific (only if data present)
            alive_section = self._alive_specific_section(systems)
            if alive_section:
                lines.extend(alive_section)
                lines.append("")

        # Methodology
        lines.extend([
            "## Methodology",
            "",
            "- Each system uses its recommended best-practice configuration",
            "- RAG+ variant gets the same LLM budget as alive for periodic maintenance",
            "- Hard ground truth: deterministic substring matching",
            "- Soft ground truth (pattern_recognition, emotional_context): 3 LLM judges, majority vote",
            "- Identity consistency reported separately (only alive-memory supports it)",
            "- All competitor versions pinned in requirements.txt",
            "",
            "## Reproduction",
            "",
            "```bash",
            "# Generate data",
            "python -m benchmarks generate --scenario research_assistant",
            "",
            "# Run all systems with 5 seeds",
            "python -m benchmarks run --stream research_assistant_10k --all --seeds 42,123,456,789,1337",
            "",
            "# Generate this report",
            "python -m benchmarks report --results-dir benchmarks/results/",
            "```",
        ])

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("\n".join(lines))
        print(f"Report saved to {output_path}")

    def _summary_table(self, systems: dict[str, list[dict]]) -> list[str]:
        """Generate the summary comparison table."""
        if not systems:
            return ["No results found."]

        system_ids = sorted(systems.keys())

        # Collect metrics per system
        metrics_by_system: dict[str, dict[str, AggregatedMetric]] = {}

        for sys_id in system_ids:
            runs = systems[sys_id]
            f1_values = []
            contra_values = []
            cost_values = []
            storage_values = []
            mem_count_values = []

            for run in runs:
                fm = run.get("final_metrics", {})
                fs = run.get("final_stats", {})
                summary = fm.get("recall_summary", {})

                f1_values.append(summary.get("f1", 0.0))

                contras = fm.get("contradiction_results", [])
                if contras:
                    acc = sum(1 for c in contras if c.get("update_accuracy", 0) > 0) / len(contras)
                    contra_values.append(acc)

                storage_values.append(fs.get("storage_bytes", 0))
                mem_count_values.append(fs.get("memory_count", 0))

                # Cost estimate from tokens
                tokens = fs.get("total_tokens", 0)
                cost = tokens / 1_000_000 * 3.0  # rough estimate
                cost_values.append(cost)

            metrics_by_system[sys_id] = {
                "Recall F1": _aggregate(f1_values),
                "Contradiction": _aggregate(contra_values) if contra_values else _aggregate([0.0]),
                "Cost ($)": _aggregate(cost_values),
                "Storage": _aggregate(storage_values),
                "Memories": _aggregate(mem_count_values),
            }

        # Build table
        lines = ["### Summary Table", ""]
        metric_names = ["Recall F1", "Contradiction", "Cost ($)", "Storage", "Memories"]

        # Header
        header = "| Metric | " + " | ".join(system_ids) + " |"
        sep = "|--------|" + "|".join(["--------"] * len(system_ids)) + "|"
        lines.extend([header, sep])

        for metric_name in metric_names:
            cells = []
            for sys_id in system_ids:
                agg = metrics_by_system[sys_id].get(metric_name)
                if agg and agg.n > 0:
                    if metric_name == "Storage":
                        val = agg.mean
                        if val > 1_000_000:
                            cells.append(f"{val / 1_000_000:.1f} MB")
                        elif val > 1_000:
                            cells.append(f"{val / 1_000:.0f} KB")
                        else:
                            cells.append(f"{val:.0f} B")
                    elif metric_name == "Memories":
                        cells.append(f"{agg.mean:,.0f}")
                    elif metric_name == "Cost ($)":
                        cells.append(f"${agg.mean:.2f}")
                    else:
                        cells.append(str(agg))
                else:
                    cells.append("—")

            lines.append(f"| {metric_name} | " + " | ".join(cells) + " |")

        return lines

    def _category_breakdown(self, systems: dict[str, list[dict]]) -> list[str]:
        """Generate per-category recall breakdown."""
        lines = ["### Recall by Category", ""]

        system_ids = sorted(systems.keys())
        all_categories: set[str] = set()

        # Collect all categories
        for sys_id in system_ids:
            for run in systems[sys_id]:
                fm = run.get("final_metrics", {})
                cats = fm.get("recall_by_category", {})
                all_categories.update(cats.keys())

        if not all_categories:
            return lines + ["No category data available."]

        categories = sorted(all_categories)

        header = "| Category | " + " | ".join(system_ids) + " |"
        sep = "|----------|" + "|".join(["--------"] * len(system_ids)) + "|"
        lines.extend([header, sep])

        for cat in categories:
            cells = []
            for sys_id in system_ids:
                values = []
                for run in systems[sys_id]:
                    fm = run.get("final_metrics", {})
                    cats = fm.get("recall_by_category", {})
                    cat_data = cats.get(cat, {})
                    values.append(cat_data.get("f1", 0.0))

                agg = _aggregate(values) if values else _aggregate([0.0])
                cells.append(str(agg))

            lines.append(f"| {cat} | " + " | ".join(cells) + " |")

        return lines

    def _degradation_section(self, systems: dict[str, list[dict]]) -> list[str]:
        """Generate degradation curve data."""
        lines = ["### Scale Degradation", ""]

        system_ids = sorted(systems.keys())

        # Collect F1 at each measurement point
        all_cycles: set[int] = set()
        for sys_id in system_ids:
            for run in systems[sys_id]:
                for point in run.get("metrics_over_time", []):
                    all_cycles.add(point["cycle"])

        if not all_cycles:
            return lines + ["No degradation data available."]

        cycles = sorted(all_cycles)

        header = "| Cycle | " + " | ".join(system_ids) + " |"
        sep = "|-------|" + "|".join(["--------"] * len(system_ids)) + "|"
        lines.extend([header, sep])

        for cycle in cycles:
            cells = []
            for sys_id in system_ids:
                values = []
                for run in systems[sys_id]:
                    for point in run.get("metrics_over_time", []):
                        if point["cycle"] == cycle:
                            summary = point.get("recall_summary", {})
                            values.append(summary.get("f1", 0.0))

                agg = _aggregate(values) if values else _aggregate([0.0])
                cells.append(str(agg))

            lines.append(f"| {cycle:,} | " + " | ".join(cells) + " |")

        return lines

    def _resource_section(self, systems: dict[str, list[dict]]) -> list[str]:
        """Generate resource efficiency comparison."""
        lines = ["### Resource Efficiency", ""]

        system_ids = sorted(systems.keys())

        header = "| Metric | " + " | ".join(system_ids) + " |"
        sep = "|--------|" + "|".join(["--------"] * len(system_ids)) + "|"
        lines.extend([header, sep])

        for metric_name, key in [
            ("Wall time (s)", "wall_time_seconds"),
            ("LLM calls", "total_llm_calls"),
            ("Tokens", "total_tokens"),
        ]:
            cells = []
            for sys_id in system_ids:
                values = []
                for run in systems[sys_id]:
                    if key == "wall_time_seconds":
                        values.append(run.get(key, 0))
                    else:
                        fs = run.get("final_stats", {})
                        values.append(fs.get(key, 0))

                agg = _aggregate(values) if values else _aggregate([0.0])
                if metric_name == "Wall time (s)":
                    cells.append(f"{agg.mean:.1f}s")
                elif metric_name == "Tokens":
                    cells.append(f"{agg.mean:,.0f}")
                else:
                    cells.append(f"{agg.mean:,.0f}")

            lines.append(f"| {metric_name} | " + " | ".join(cells) + " |")

        # Latency data
        for lat_name in ["ingest", "recall", "consolidate"]:
            cells = []
            for sys_id in system_ids:
                values = []
                for run in systems[sys_id]:
                    lat_data = run.get("latencies", {}).get(lat_name, {})
                    values.append(lat_data.get("mean_ms", 0))

                agg = _aggregate(values) if values else _aggregate([0.0])
                cells.append(f"{agg.mean:.1f}ms")

            lines.append(f"| Avg {lat_name} latency | " + " | ".join(cells) + " |")

        return lines

    def _ranking_quality_section(self, systems: dict[str, list[dict]]) -> list[str]:
        """Generate NDCG ranking quality table."""
        lines = ["### Ranking Quality", ""]

        system_ids = sorted(systems.keys())

        # Check if any system has NDCG-relevant data (recall_by_category)
        has_data = False
        for sys_id in system_ids:
            for run in systems[sys_id]:
                fm = run.get("final_metrics", {})
                if fm.get("recall_by_category"):
                    has_data = True
                    break
            if has_data:
                break

        if not has_data:
            return lines + ["No ranking quality data available."]

        header = "| Metric | " + " | ".join(system_ids) + " |"
        sep = "|--------|" + "|".join(["--------"] * len(system_ids)) + "|"
        lines.extend([header, sep])

        # MRR from recall_summary
        cells = []
        for sys_id in system_ids:
            values = []
            for run in systems[sys_id]:
                fm = run.get("final_metrics", {})
                values.append(fm.get("recall_summary", {}).get("mrr", 0.0))
            agg = _aggregate(values) if values else _aggregate([0.0])
            cells.append(str(agg))
        lines.append("| MRR | " + " | ".join(cells) + " |")

        # Per-category MRR
        all_categories: set[str] = set()
        for sys_id in system_ids:
            for run in systems[sys_id]:
                fm = run.get("final_metrics", {})
                all_categories.update(fm.get("recall_by_category", {}).keys())

        for cat in sorted(all_categories):
            cells = []
            for sys_id in system_ids:
                values = []
                for run in systems[sys_id]:
                    fm = run.get("final_metrics", {})
                    cat_data = fm.get("recall_by_category", {}).get(cat, {})
                    values.append(cat_data.get("mrr", 0.0))
                agg = _aggregate(values) if values else _aggregate([0.0])
                cells.append(str(agg))
            lines.append(f"| MRR ({cat}) | " + " | ".join(cells) + " |")

        return lines

    def _reliability_section(self, systems: dict[str, list[dict]]) -> list[str]:
        """Generate reliability section: hallucination + entity confusion."""
        lines = ["### Reliability", ""]

        system_ids = sorted(systems.keys())

        # Check for traceability and entity confusion data
        has_trace = any(
            run.get("final_metrics", {}).get("traceability_results")
            for sys_id in system_ids
            for run in systems[sys_id]
        )
        has_confusion = any(
            run.get("final_metrics", {}).get("entity_confusion_results")
            for sys_id in system_ids
            for run in systems[sys_id]
        )

        if not has_trace and not has_confusion:
            return lines + ["No reliability data available."]

        header = "| Metric | " + " | ".join(system_ids) + " |"
        sep = "|--------|" + "|".join(["--------"] * len(system_ids)) + "|"
        lines.extend([header, sep])

        # Hallucination rate
        if has_trace:
            cells = []
            for sys_id in system_ids:
                values = []
                for run in systems[sys_id]:
                    traces = run.get("final_metrics", {}).get("traceability_results", [])
                    if traces:
                        traceable = sum(1 for t in traces if t.get("traceable", False))
                        values.append(1.0 - (traceable / len(traces)))
                    else:
                        values.append(0.0)
                agg = _aggregate(values) if values else _aggregate([0.0])
                cells.append(str(agg))
            lines.append("| Fabrication rate | " + " | ".join(cells) + " |")

        # Entity confusion rate
        if has_confusion:
            cells = []
            for sys_id in system_ids:
                values = []
                for run in systems[sys_id]:
                    confusions = run.get("final_metrics", {}).get("entity_confusion_results", [])
                    if confusions:
                        confused = sum(1 for c in confusions if c.get("confusion_count", 0) > 0)
                        values.append(confused / len(confusions))
                    else:
                        values.append(0.0)
                agg = _aggregate(values) if values else _aggregate([0.0])
                cells.append(str(agg))
            lines.append("| Entity confusion rate | " + " | ".join(cells) + " |")

        return lines

    def _efficiency_section(self, systems: dict[str, list[dict]]) -> list[str]:
        """Generate efficiency section: consolidation ROI + graceful degradation."""
        lines = ["### Efficiency", ""]

        system_ids = sorted(systems.keys())

        header = "| Metric | " + " | ".join(system_ids) + " |"
        sep = "|--------|" + "|".join(["--------"] * len(system_ids)) + "|"
        lines.extend([header, sep])

        # F1 improvement (final - first)
        cells = []
        for sys_id in system_ids:
            values = []
            for run in systems[sys_id]:
                mot = run.get("metrics_over_time", [])
                if len(mot) >= 2:
                    first_f1 = mot[0].get("recall_summary", {}).get("f1", 0.0)
                    final_f1 = mot[-1].get("recall_summary", {}).get("f1", 0.0)
                    values.append(final_f1 - first_f1)
                else:
                    values.append(0.0)
            agg = _aggregate(values) if values else _aggregate([0.0])
            cells.append(f"{agg.mean:+.3f}")
        lines.append("| F1 improvement | " + " | ".join(cells) + " |")

        # Quality retention (final F1 / first F1)
        cells = []
        for sys_id in system_ids:
            values = []
            for run in systems[sys_id]:
                mot = run.get("metrics_over_time", [])
                if len(mot) >= 2:
                    first_f1 = mot[0].get("recall_summary", {}).get("f1", 0.0)
                    final_f1 = mot[-1].get("recall_summary", {}).get("f1", 0.0)
                    values.append(final_f1 / first_f1 if first_f1 > 0 else 0.0)
                else:
                    values.append(0.0)
            agg = _aggregate(values) if values else _aggregate([0.0])
            cells.append(f"{agg.mean:.2f}x")
        lines.append("| Quality retention | " + " | ".join(cells) + " |")

        # p999 recall latency
        cells = []
        for sys_id in system_ids:
            values = []
            for run in systems[sys_id]:
                lat = run.get("latencies", {}).get("recall", {})
                values.append(lat.get("p999_ms", lat.get("max_ms", 0)))
            agg = _aggregate(values) if values else _aggregate([0.0])
            cells.append(f"{agg.mean:.1f}ms")
        lines.append("| p999 recall latency | " + " | ".join(cells) + " |")

        return lines

    def _alive_specific_section(self, systems: dict[str, list[dict]]) -> list[str]:
        """Generate alive-memory specific section (only if data present)."""
        # Check if any system has adapter_data
        has_alive_data = False
        for _sys_id, runs in systems.items():
            for run in runs:
                adapter_data = run.get("final_metrics", {}).get("adapter_data", {})
                if adapter_data.get("salience_map") or adapter_data.get("consolidation_reports"):
                    has_alive_data = True
                    break
            if has_alive_data:
                break

        # Check for tier distribution
        has_tiers = any(
            run.get("final_metrics", {}).get("tier_distribution")
            for runs in systems.values()
            for run in runs
        )

        if not has_alive_data and not has_tiers:
            return []

        lines = ["### alive-memory Specific", ""]

        # Salience calibration
        if has_alive_data:
            lines.append("**Salience & Consolidation:**")
            lines.append("")
            for sys_id, runs in sorted(systems.items()):
                for run in runs:
                    adapter_data = run.get("final_metrics", {}).get("adapter_data", {})
                    salience_map = adapter_data.get("salience_map", {})
                    total_dreams = adapter_data.get("total_dreams", 0)
                    total_reflections = adapter_data.get("total_reflections", 0)
                    reports = adapter_data.get("consolidation_reports", [])

                    if salience_map or total_dreams or total_reflections:
                        lines.append(f"- **{sys_id}**: "
                                     f"{len(salience_map)} events with salience data, "
                                     f"{total_dreams} dreams, "
                                     f"{total_reflections} reflections, "
                                     f"{len(reports)} consolidation reports")
            lines.append("")

        # Tier distribution
        if has_tiers:
            lines.append("**Memory Tier Distribution:**")
            lines.append("")
            for sys_id, runs in sorted(systems.items()):
                for run in runs:
                    tier_dist = run.get("final_metrics", {}).get("tier_distribution", {})
                    if tier_dist:
                        total = sum(tier_dist.values())
                        parts = [f"{tier}: {count/total:.0%}" for tier, count in sorted(tier_dist.items())]
                        lines.append(f"- **{sys_id}**: " + ", ".join(parts))
            lines.append("")

        return lines

    def generate_charts(self, output_dir: str) -> None:
        """Generate publication-quality charts using matplotlib."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib required for charts: pip install matplotlib")
            return

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        for stream_name, systems in self.results.items():
            self._chart_degradation(plt, systems, stream_name, out)
            self._chart_cost_quality(plt, systems, stream_name, out)
            self._chart_roi_frontier(plt, systems, stream_name, out)
            self._chart_hallucination(plt, systems, stream_name, out)

        print(f"Charts saved to {out}/")

    def _chart_degradation(self, plt, systems, stream_name, out_dir):
        """Degradation curve: F1 vs cycles."""
        fig, ax = plt.subplots(figsize=(10, 6))

        for sys_id in sorted(systems.keys()):
            # Aggregate across seeds
            cycle_values: dict[int, list[float]] = {}
            for run in systems[sys_id]:
                for point in run.get("metrics_over_time", []):
                    cycle = point["cycle"]
                    f1 = point.get("recall_summary", {}).get("f1", 0.0)
                    cycle_values.setdefault(cycle, []).append(f1)

            if not cycle_values:
                continue

            cycles = sorted(cycle_values.keys())
            means = [statistics.mean(cycle_values[c]) for c in cycles]

            ax.plot(cycles, means, marker="o", markersize=4, label=sys_id)

            # CI bands if multiple seeds
            if any(len(v) > 1 for v in cycle_values.values()):
                lows = []
                highs = []
                for c in cycles:
                    agg = _aggregate(cycle_values[c])
                    lows.append(agg.ci_low)
                    highs.append(agg.ci_high)
                ax.fill_between(cycles, lows, highs, alpha=0.15)

        ax.set_xlabel("Cycles")
        ax.set_ylabel("Recall F1")
        ax.set_title(f"Recall F1 Over Time — {stream_name}")
        ax.legend()
        ax.set_ylim(0, 1.05)
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(str(out_dir / f"degradation_{stream_name}.png"), dpi=150)
        plt.close(fig)

    def _chart_cost_quality(self, plt, systems, stream_name, out_dir):
        """Cost vs quality frontier."""
        fig, ax = plt.subplots(figsize=(8, 6))

        for sys_id in sorted(systems.keys()):
            f1_values = []
            cost_values = []
            for run in systems[sys_id]:
                fm = run.get("final_metrics", {})
                fs = run.get("final_stats", {})
                f1_values.append(fm.get("recall_summary", {}).get("f1", 0.0))
                tokens = fs.get("total_tokens", 0)
                cost_values.append(tokens / 1_000_000 * 3.0)

            if f1_values:
                f1_mean = statistics.mean(f1_values)
                cost_mean = statistics.mean(cost_values)
                ax.scatter(cost_mean, f1_mean, s=100, zorder=5)
                ax.annotate(
                    sys_id,
                    (cost_mean, f1_mean),
                    textcoords="offset points",
                    xytext=(8, 5),
                    fontsize=9,
                )

        ax.set_xlabel("Estimated Cost ($)")
        ax.set_ylabel("Recall F1 @final")
        ax.set_title(f"Cost vs Quality — {stream_name}")
        ax.set_ylim(0, 1.05)
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(str(out_dir / f"cost_quality_{stream_name}.png"), dpi=150)
        plt.close(fig)

    def _chart_roi_frontier(self, plt, systems, stream_name, out_dir):
        """ROI frontier: F1 improvement vs cost scatter."""
        fig, ax = plt.subplots(figsize=(8, 6))

        has_data = False
        for sys_id in sorted(systems.keys()):
            improvements = []
            costs = []
            for run in systems[sys_id]:
                mot = run.get("metrics_over_time", [])
                fs = run.get("final_stats", {})
                if len(mot) >= 2:
                    first_f1 = mot[0].get("recall_summary", {}).get("f1", 0.0)
                    final_f1 = mot[-1].get("recall_summary", {}).get("f1", 0.0)
                    improvements.append(final_f1 - first_f1)
                    tokens = fs.get("total_tokens", 0)
                    costs.append(tokens / 1_000_000 * 3.0)

            if improvements:
                has_data = True
                imp_mean = statistics.mean(improvements)
                cost_mean = statistics.mean(costs)
                ax.scatter(cost_mean, imp_mean, s=100, zorder=5)
                ax.annotate(
                    sys_id,
                    (cost_mean, imp_mean),
                    textcoords="offset points",
                    xytext=(8, 5),
                    fontsize=9,
                )

        if not has_data:
            plt.close(fig)
            return

        ax.set_xlabel("Estimated Cost ($)")
        ax.set_ylabel("F1 Improvement (final - first)")
        ax.set_title(f"ROI Frontier — {stream_name}")
        ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(str(out_dir / f"roi_frontier_{stream_name}.png"), dpi=150)
        plt.close(fig)

    def _chart_hallucination(self, plt, systems, stream_name, out_dir):
        """Hallucination comparison: bar chart of fabrication rates."""
        sys_ids = []
        fab_rates = []

        for sys_id in sorted(systems.keys()):
            rates = []
            for run in systems[sys_id]:
                traces = run.get("final_metrics", {}).get("traceability_results", [])
                if traces:
                    traceable = sum(1 for t in traces if t.get("traceable", False))
                    rates.append(1.0 - (traceable / len(traces)))
            if rates:
                sys_ids.append(sys_id)
                fab_rates.append(statistics.mean(rates))

        if not sys_ids:
            return

        fig, ax = plt.subplots(figsize=(8, 5))
        bars = ax.bar(sys_ids, fab_rates, color="#e74c3c", alpha=0.8)

        # Add value labels on bars
        for bar, rate in zip(bars, fab_rates, strict=False):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.01,
                f"{rate:.1%}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

        ax.set_ylabel("Fabrication Rate")
        ax.set_title(f"Hallucination Comparison — {stream_name}")
        ax.set_ylim(0, max(fab_rates) * 1.3 if fab_rates else 1.0)
        ax.grid(True, alpha=0.3, axis="y")

        fig.tight_layout()
        fig.savefig(str(out_dir / f"hallucination_{stream_name}.png"), dpi=150)
        plt.close(fig)
