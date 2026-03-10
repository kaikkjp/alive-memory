"""Report generator for evolve results."""

from __future__ import annotations

from alive_memory.evolve.types import EvolveResult, EvolveScore, FailureCategory, IterationRecord


def generate_report(result: EvolveResult) -> str:
    """Generate a markdown report from evolve results.

    Sections:
    1. Summary — iterations, promoted count, elapsed time, improvement
    2. Per-Split Scores — train / held_out / production comparison
    3. Per-Category Breakdown — failure category pass rates
    4. Iteration Log — all iterations with scores and promotion status
    5. Source Changes Summary — files modified with brief diff excerpts
    """
    lines: list[str] = []

    # ── 1. Summary ────────────────────────────────────────────────
    lines.append("# Evolve Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")

    promoted_count = sum(1 for i in result.iterations if i.promoted)
    lines.append(f"- **Total iterations:** {result.total_iterations}")
    lines.append(f"- **Promoted:** {promoted_count}")
    lines.append(f"- **Elapsed time:** {_format_time(result.elapsed_seconds)}")

    baseline_composite = result.baseline_score.composite if result.baseline_score else None
    best_composite = result.best_score.composite if result.best_score else None

    if baseline_composite is not None:
        lines.append(f"- **Baseline composite:** {baseline_composite:.4f}")
    if best_composite is not None:
        lines.append(f"- **Best composite:** {best_composite:.4f}")

    if baseline_composite is not None and best_composite is not None and baseline_composite > 0:
        improvement = (baseline_composite - best_composite) / baseline_composite * 100
        lines.append(f"- **Improvement:** {improvement:.1f}%")
    else:
        lines.append("- **Improvement:** N/A")

    if result.best_score:
        overfit = result.best_score.overfitting_signal
        if abs(overfit) < 0.01:
            overfit_label = "negligible"
        elif overfit < 0:
            overfit_label = f"low ({overfit:+.4f})"
        else:
            overfit_label = f"**warning** ({overfit:+.4f})"
        lines.append(f"- **Overfitting signal:** {overfit_label}")

    lines.append("")

    # ── 2. Per-Split Scores ───────────────────────────────────────
    if result.baseline_score and result.best_score:
        lines.append("## Per-Split Scores")
        lines.append("")
        lines.append("| Split | Baseline | Best | Delta |")
        lines.append("|---|---|---|---|")
        for split_name in ("train", "held_out", "production"):
            baseline_split = getattr(result.baseline_score, split_name)
            best_split = getattr(result.best_score, split_name)
            b_score = baseline_split.aggregate_score
            best_s = best_split.aggregate_score
            delta = best_s - b_score
            direction = "improved" if delta < 0 else ("regressed" if delta > 0 else "same")
            lines.append(
                f"| {split_name} | {b_score:.4f} | {best_s:.4f} | "
                f"{delta:+.4f} ({direction}) |"
            )
        lines.append("")

    # ── 3. Per-Category Breakdown ─────────────────────────────────
    if result.baseline_score and result.best_score:
        baseline_cats = _category_stats(result.baseline_score)
        best_cats = _category_stats(result.best_score)
        all_cats = sorted(set(baseline_cats.keys()) | set(best_cats.keys()))

        if all_cats:
            lines.append("## Per-Category Breakdown")
            lines.append("")
            lines.append("| Category | Cases | Baseline Pass Rate | Best Pass Rate | Status |")
            lines.append("|---|---|---|---|---|")
            for cat in all_cats:
                b_total, b_pass = baseline_cats.get(cat, (0, 0))
                best_total, best_pass = best_cats.get(cat, (0, 0))
                total = max(b_total, best_total)
                b_rate = b_pass / b_total * 100 if b_total else 0
                best_rate = best_pass / best_total * 100 if best_total else 0
                if best_rate > b_rate:
                    status = "improved"
                elif best_rate < b_rate:
                    status = "regressed"
                else:
                    status = "same"
                lines.append(
                    f"| {cat} | {total} | {b_rate:.0f}% | {best_rate:.0f}% | {status} |"
                )
            lines.append("")

    # ── 4. Iteration Log ──────────────────────────────────────────
    if result.iterations:
        lines.append("## Iteration Log")
        lines.append("")
        lines.append("| Iter | Composite | Promoted | Description | Time |")
        lines.append("|---|---|---|---|---|")
        for it in result.iterations:
            composite = f"{it.score.composite:.4f}" if it.score else "N/A"
            promoted_marker = "**Y**" if it.promoted else ""
            desc = it.failure_analysis[:60] if it.failure_analysis else ""
            elapsed = f"{it.elapsed_seconds:.1f}s"
            lines.append(
                f"| {it.iteration} | {composite} | {promoted_marker} | {desc} | {elapsed} |"
            )
        lines.append("")

    # ── 5. Source Changes Summary ─────────────────────────────────
    if result.source_diffs:
        lines.append("## Source Changes Summary")
        lines.append("")
        for filepath, diff in sorted(result.source_diffs.items()):
            lines.append(f"### {filepath}")
            lines.append("")
            # Show first few lines of the diff as a preview
            diff_lines = diff.splitlines()
            preview = diff_lines[:10]
            lines.append("```diff")
            lines.extend(preview)
            if len(diff_lines) > 10:
                lines.append(f"... ({len(diff_lines) - 10} more lines)")
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────


def _category_stats(score: EvolveScore) -> dict[str, tuple[int, int]]:
    """Collect per-category (total, pass_count) from all splits.

    A case "passes" when its composite score is below 0.5 (better than chance).
    """
    cats: dict[str, list[float]] = {}
    for split in (score.train, score.held_out, score.production):
        for cr in split.case_results:
            cats.setdefault(cr.category, []).append(cr.score.composite)
    result: dict[str, tuple[int, int]] = {}
    for cat, scores in cats.items():
        total = len(scores)
        passed = sum(1 for s in scores if s < 0.5)
        result[cat] = (total, passed)
    return result


def _format_time(seconds: float) -> str:
    """Format seconds into a human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"
