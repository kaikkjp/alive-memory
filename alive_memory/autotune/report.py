"""Markdown report generation for autotune results."""

from __future__ import annotations

from alive_memory.autotune.types import AutotuneResult


def generate_report(result: AutotuneResult) -> str:
    """Generate a markdown report from an AutotuneResult."""
    lines = [
        "# AutoConfig Tuning Report",
        "",
        "## Summary",
        f"- Iterations: {result.total_iterations}",
        f"- Best composite score: {result.best_composite:.4f} (baseline: {result.baseline_composite:.4f})",
        f"- Improvement: {result.improvement_pct:.1f}%",
        f"- Total time: {_format_time(result.elapsed_seconds)}",
        "",
    ]

    # Best config changes vs baseline
    if result.experiments:
        best_exp = None
        for exp in result.experiments:
            if exp.is_best:
                best_exp = exp
        if best_exp and best_exp.config_diff:
            lines.append("## Best Configuration Changes")
            lines.append("")
            lines.append("| Parameter | Value |")
            lines.append("|---|---|")
            for key, val in sorted(best_exp.config_diff.items()):
                lines.append(f"| {key} | {val} |")
            lines.append("")

    # Per-scenario scores for the best experiment
    best_scores = None
    for exp in reversed(result.experiments):
        if exp.is_best:
            best_scores = exp.scores
            break

    if best_scores:
        lines.append("## Per-Scenario Scores")
        lines.append("")
        lines.append("| Scenario | Composite | Recall Precision | Recall Completeness |")
        lines.append("|---|---|---|---|")
        for name, score in sorted(best_scores.items()):
            lines.append(
                f"| {name} | {score.composite:.4f} | "
                f"{score.recall_precision:.2f} | {score.recall_completeness:.2f} |"
            )
        lines.append("")

    # Parameter sensitivity
    param_mutations: dict[str, list[float]] = {}
    for exp in result.experiments:
        for key in exp.config_diff:
            if key.startswith("_"):
                continue
            param_mutations.setdefault(key, []).append(
                exp.composite - result.baseline_composite
            )

    if param_mutations:
        lines.append("## Parameter Sensitivity")
        lines.append("")
        lines.append("| Parameter | Times Mutated | Avg Score Delta |")
        lines.append("|---|---|---|")
        for key, deltas in sorted(
            param_mutations.items(), key=lambda x: sum(x[1]) / len(x[1])
        ):
            avg = sum(deltas) / len(deltas)
            direction = "improved" if avg < 0 else "degraded"
            lines.append(f"| {key} | {len(deltas)} | {avg:+.4f} ({direction}) |")
        lines.append("")

    # Experiment log (last 10)
    lines.append("## Recent Experiments (last 10)")
    lines.append("")
    lines.append("| Iter | Composite | Best? | Strategy | Time |")
    lines.append("|---|---|---|---|---|")
    for exp in result.experiments[-10:]:
        best_marker = "Y" if exp.is_best else ""
        lines.append(
            f"| {exp.iteration} | {exp.composite:.4f} | {best_marker} | "
            f"{exp.strategy} | {exp.elapsed_seconds:.1f}s |"
        )
    lines.append("")

    return "\n".join(lines)


def _format_time(seconds: float) -> str:
    """Format seconds into human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"
