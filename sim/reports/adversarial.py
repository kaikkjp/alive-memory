"""sim.reports.adversarial — Adversarial episode report export.

Exports adversarial_episodes.json alongside other metric reports,
containing per-episode pass/fail results and aggregate pass rates
by adversarial type.

Usage:
    from sim.reports.adversarial import export_adversarial_report
    export_adversarial_report(scorer, output_dir="sim/results/")
"""

from __future__ import annotations

import json
from pathlib import Path

from sim.metrics.memory_score import AdversarialScorer


def export_adversarial_report(
    scorer: AdversarialScorer,
    output_dir: str | Path,
) -> Path:
    """Export adversarial episode results to JSON.

    Args:
        scorer: AdversarialScorer with recorded episodes.
        output_dir: Directory to write the report to.

    Returns:
        Path to the written JSON file.
    """
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    metrics = scorer.compute_metrics()
    episodes = [ep.to_dict() for ep in scorer.episodes]

    report = {
        "summary": metrics,
        "episodes": episodes,
    }

    filepath = path / "adversarial_episodes.json"
    filepath.write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    return filepath


def print_adversarial_summary(scorer: AdversarialScorer):
    """Print a human-readable adversarial episode summary to stdout."""
    metrics = scorer.compute_metrics()
    total = metrics["total_episodes"]

    if total == 0:
        print("[Adversarial] No adversarial episodes recorded.")
        return

    print(f"\n[Adversarial] {total} episodes evaluated:")
    for ctype in ("doppelganger", "preference_drift", "conflict"):
        info = metrics["episodes_by_type"].get(ctype, {})
        passed = info.get("passed", 0)
        total_t = info.get("total", 0)
        rate = info.get("rate", 0.0)
        if total_t > 0:
            status = "PASS" if rate >= 0.7 else "WARN"
            print(f"  {ctype:>20s}: {passed}/{total_t} ({rate:.1%}) [{status}]")

    overall = metrics["adversarial_overall_pass_rate"]
    overall_status = "PASS" if overall >= 0.7 else "FAIL"
    print(f"  {'overall':>20s}: {overall:.1%} [target >70%: {overall_status}]")
