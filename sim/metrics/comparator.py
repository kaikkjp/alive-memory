"""sim.metrics.comparator — Compare metrics across simulation runs.

Generates comparison tables for the research paper:
- Table 1: ALIVE vs Baselines
- Table 2: Ablation study results

No external dependencies (no pandas). Uses plain dicts and CSV.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class MetricsComparator:
    """Compares metrics across simulation runs. Generates paper tables."""

    def __init__(self, results: dict[str, dict]):
        """
        Args:
            results: Dict mapping variant name to metrics dict.
                     e.g. {"full": {...}, "stateless": {...}, "react": {...}}
        """
        self.results = results

    @classmethod
    def from_results_dir(cls, results_dir: str | Path) -> MetricsComparator:
        """Load all result JSON files from a directory."""
        path = Path(results_dir)
        results = {}
        for f in sorted(path.glob("*.json")):
            data = json.loads(f.read_text())
            variant = data.get("variant", f.stem)
            results[variant] = data
        return cls(results)

    def comparison_table(self) -> list[dict]:
        """Generate Table 1: ALIVE vs Baselines comparison."""
        rows = []
        metrics_keys = [
            ("m2_initiative_rate", "Initiative (%)"),
            ("m3_entropy", "Entropy"),
            ("m4_knowledge", "Knowledge"),
            ("m5_recall", "Recall (%)"),
            ("m6_taste", "Taste"),
            ("m7_emotional_range", "Emotional Range"),
            ("m9_unprompted_memories", "Unprompted Memories"),
            ("m10_depth_gradient", "Depth Gradient"),
        ]

        for variant, data in self.results.items():
            row = {"System": variant}
            metrics = data if "m1_uptime" in data else data.get("metrics", {})
            for key, label in metrics_keys:
                row[label] = metrics.get(key, "N/A")
            rows.append(row)

        return rows

    def ablation_table(self) -> list[dict]:
        """Generate Table 2: Ablation study results.

        Shows the delta from full ALIVE for each ablated variant.
        """
        if "full" not in self.results:
            return self.comparison_table()

        full_metrics = self.results["full"]
        if "m1_uptime" not in full_metrics:
            full_metrics = full_metrics.get("metrics", {})

        rows = []
        metrics_keys = [
            ("m2_initiative_rate", "Initiative (%)"),
            ("m3_entropy", "Entropy"),
            ("m7_emotional_range", "Emotional Range"),
            ("m9_unprompted_memories", "Unprompted Memories"),
        ]

        for variant, data in self.results.items():
            metrics = data if "m1_uptime" in data else data.get("metrics", {})
            row = {"Variant": variant}
            for key, label in metrics_keys:
                full_val = full_metrics.get(key, 0)
                this_val = metrics.get(key, 0)
                if isinstance(full_val, (int, float)) and isinstance(this_val, (int, float)):
                    delta = this_val - full_val
                    row[label] = this_val
                    row[f"{label} (delta)"] = round(delta, 3)
                else:
                    row[label] = this_val
                    row[f"{label} (delta)"] = "N/A"
            rows.append(row)

        return rows

    def export_csv(self, output_dir: str | Path):
        """Export comparison tables as CSV files."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        # Table 1
        table1 = self.comparison_table()
        if table1:
            self._write_csv(path / "table1_baselines.csv", table1)

        # Table 2
        table2 = self.ablation_table()
        if table2:
            self._write_csv(path / "table2_ablation.csv", table2)

    def export_json(self, output_dir: str | Path):
        """Export raw metrics as JSON."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        output = {
            "comparison": self.comparison_table(),
            "ablation": self.ablation_table(),
            "raw": self.results,
        }
        (path / "metrics_comparison.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False)
        )

    @staticmethod
    def _write_csv(filepath: Path, rows: list[dict]):
        """Write a list of dicts as a CSV file."""
        if not rows:
            return
        fieldnames = list(rows[0].keys())
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
