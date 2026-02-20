"""sim.metrics.exporter — Export simulation data for paper figures.

Generates data files (CSV) that can be plotted externally.
Does not depend on matplotlib — keeps the dependency footprint minimal.
Researchers can use their preferred plotting tool.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class FigureExporter:
    """Export simulation data for paper figures."""

    @staticmethod
    def longitudinal_curves(result: dict, output_dir: str | Path):
        """Export data for Figure 1: Knowledge/taste/entropy over cycles."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        drives = result.get("drives_history", [])
        cycles = result.get("cycles", [])

        # Export drives timeline
        if drives:
            _write_csv(
                path / "fig1_drives_timeline.csv",
                drives,
                fieldnames=["cycle", "mood_valence", "mood_arousal", "energy",
                            "social_hunger", "curiosity", "expression_need"],
            )

        # Export action counts per window
        window = 50  # aggregate per 50 cycles
        action_windows = []
        for start in range(0, len(cycles), window):
            chunk = cycles[start:start + window]
            types = {}
            for c in chunk:
                t = c.get("type", "idle")
                types[t] = types.get(t, 0) + 1
            action_windows.append({
                "cycle_start": start,
                "idle": types.get("idle", 0),
                "dialogue": types.get("dialogue", 0),
                "browse": types.get("browse", 0),
                "post": types.get("post", 0),
                "journal": types.get("journal", 0),
                "sleep": types.get("sleep", 0),
            })

        if action_windows:
            _write_csv(
                path / "fig1_action_distribution.csv",
                action_windows,
                fieldnames=["cycle_start", "idle", "dialogue", "browse",
                            "post", "journal", "sleep"],
            )

    @staticmethod
    def death_spiral(result: dict, output_dir: str | Path):
        """Export data for Figure 4: Valence death spiral."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        drives = result.get("drives_history", [])
        if drives:
            valence_data = [
                {"cycle": d.get("cycle", i), "valence": d.get("mood_valence", 0)}
                for i, d in enumerate(drives)
            ]
            _write_csv(
                path / "fig4_valence_timeline.csv",
                valence_data,
                fieldnames=["cycle", "valence"],
            )

    @staticmethod
    def comparison_bar(metrics: dict[str, dict], output_dir: str | Path):
        """Export data for comparison bar charts."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        rows = []
        for variant, m in metrics.items():
            if "m1_uptime" not in m:
                m = m.get("metrics", m)
            rows.append({
                "variant": variant,
                "initiative": m.get("m2_initiative_rate", 0),
                "entropy": m.get("m3_entropy", 0),
                "knowledge": m.get("m4_knowledge", 0),
                "recall": m.get("m5_recall", 0),
                "taste": m.get("m6_taste", 0),
                "emotional_range": m.get("m7_emotional_range", 0),
            })

        if rows:
            _write_csv(
                path / "comparison_metrics.csv",
                rows,
                fieldnames=["variant", "initiative", "entropy", "knowledge",
                            "recall", "taste", "emotional_range"],
            )

    @staticmethod
    def export_all(results: dict[str, dict], output_dir: str | Path):
        """Export all figure data from multiple simulation results."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        # Individual result exports
        for variant, data in results.items():
            variant_dir = path / variant
            FigureExporter.longitudinal_curves(data, variant_dir)

            if "death_spiral" in variant:
                FigureExporter.death_spiral(data, variant_dir)

        # Combined comparison
        FigureExporter.comparison_bar(results, path)

        # Raw JSON dump
        (path / "all_results.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False, default=str)
        )


def _write_csv(filepath: Path, rows: list[dict],
               fieldnames: list[str] | None = None):
    """Write rows to CSV file."""
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
