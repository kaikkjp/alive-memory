"""Failure analyzer — generates reports from eval results for the coding agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from tools.evolve.types import CaseResult, RecallScore, SplitResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Failure clustering
# ---------------------------------------------------------------------------


@dataclass
class FailureCluster:
    """A group of related failures."""

    category: str
    count: int
    difficulty_range: str  # e.g. "3-7"
    example_case_id: str
    example_description: str  # what was expected vs what happened


def _dominant_failure_mode(score: RecallScore) -> str:
    """Identify the weakest dimension of a recall score.

    Returns a human-readable label describing the primary failure mode.
    Lower values indicate worse performance for each dimension.
    """
    dimensions = {
        "completeness": score.completeness,
        "precision": score.precision,
        "noise_rejection": score.noise_rejection,
        "ranking_quality": score.ranking_quality,
    }
    worst_dim = min(dimensions, key=dimensions.get)  # type: ignore[arg-type]
    worst_val = dimensions[worst_dim]

    labels = {
        "completeness": f"low completeness ({worst_val:.2f}) — ground-truth facts not being recalled",
        "precision": f"low precision ({worst_val:.2f}) — too much irrelevant content returned",
        "noise_rejection": f"low noise_rejection ({worst_val:.2f}) — noise/forbidden items not filtered",
        "ranking_quality": f"low ranking_quality ({worst_val:.2f}) — relevant items ranked poorly",
    }
    return labels[worst_dim]


def _describe_failure(case: CaseResult) -> str:
    """Build a description of what went wrong for a specific case.

    Examines per-query scores when available, otherwise falls back to the
    aggregate case score.
    """
    scores = case.per_query_scores if case.per_query_scores else [case.score]

    # Find the query with the worst composite score
    worst = max(scores, key=lambda s: s.composite)
    mode = _dominant_failure_mode(worst)

    parts = [mode]

    # Add secondary failures if multiple dimensions are weak
    dims = {
        "completeness": worst.completeness,
        "precision": worst.precision,
        "noise_rejection": worst.noise_rejection,
        "ranking_quality": worst.ranking_quality,
    }
    weak = [k for k, v in dims.items() if v < 0.5]
    if len(weak) > 1:
        parts.append(f"multiple weak dimensions: {', '.join(weak)}")

    if case.errors:
        parts.append(f"errors: {'; '.join(case.errors[:2])}")

    return "; ".join(parts)


def cluster_failures(
    results: list[CaseResult],
    threshold: float = 0.5,
) -> list[FailureCluster]:
    """Group failed cases by category.

    A case is "failed" if its composite score >= *threshold* (lower is better).
    Within each category, collect failures, compute difficulty range,
    pick the case with the worst score as the representative example.
    Sort clusters by count descending.
    """
    from tools.evolve.scorer import score_case

    # Partition failures by category using category-adjusted scores
    by_category: dict[str, list[CaseResult]] = {}
    for cr in results:
        if score_case(cr) >= threshold:
            by_category.setdefault(cr.category, []).append(cr)

    clusters: list[FailureCluster] = []
    for category, cases in by_category.items():
        difficulties = [c.difficulty for c in cases]
        min_d, max_d = min(difficulties), max(difficulties)
        difficulty_range = str(min_d) if min_d == max_d else f"{min_d}-{max_d}"

        # Pick the worst case as the representative example
        worst_case = max(cases, key=lambda c: c.score.composite)
        description = _describe_failure(worst_case)

        clusters.append(
            FailureCluster(
                category=category,
                count=len(cases),
                difficulty_range=difficulty_range,
                example_case_id=worst_case.case_id,
                example_description=description,
            )
        )

    # Sort by count descending, then category name for stability
    clusters.sort(key=lambda c: (-c.count, c.category))
    return clusters


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _format_score_summary(score: RecallScore) -> str:
    """One-line summary of a recall score's dimensions."""
    return (
        f"completeness={score.completeness:.2f}, "
        f"precision={score.precision:.2f}, "
        f"noise_rejection={score.noise_rejection:.2f}, "
        f"ranking={score.ranking_quality:.2f}"
    )


def generate_failure_report(
    train_result: SplitResult,
    max_clusters: int = 5,
) -> str:
    """Generate the failure analysis report that the coding agent sees.

    ONLY reports from the train split.  The agent never sees held-out or
    production failures.

    The report is the sole signal the coding agent receives about what is
    failing, so each cluster includes:

    * The dominant failure mode (completeness / precision / noise / ranking)
    * A concrete example case ID and what went wrong
    * The difficulty range to indicate whether easy or hard cases are breaking

    If there are no failures, returns a brief "All cases passed" message.
    """
    total = len(train_result.case_results)
    if total == 0:
        return "FAILURE ANALYSIS (train split, 0 cases): No eval cases to analyze."

    pass_count = train_result.pass_count
    fail_count = train_result.fail_count

    # If pass/fail counts haven't been pre-computed, derive from adjusted scores
    if pass_count + fail_count == 0:
        from tools.evolve.scorer import score_case

        fail_count = sum(
            1 for cr in train_result.case_results if score_case(cr) >= 0.5
        )
        pass_count = total - fail_count

    pass_pct = (pass_count / total) * 100 if total else 0
    fail_pct = (fail_count / total) * 100 if total else 0

    lines: list[str] = [
        f"FAILURE ANALYSIS (train split, {total} cases):",
        "",
        f"Passed: {pass_count}/{total} ({pass_pct:.0f}%)",
        f"Failed: {fail_count}/{total} ({fail_pct:.0f}%)",
    ]

    if fail_count == 0:
        lines.append("")
        lines.append("All cases passed. No failure clusters to report.")
        return "\n".join(lines)

    clusters = cluster_failures(train_result.case_results)
    if not clusters:
        lines.append("")
        lines.append("All cases passed. No failure clusters to report.")
        return "\n".join(lines)

    # Find the actual CaseResult for each cluster's example so we can
    # include score details
    results_by_id = {cr.case_id: cr for cr in train_result.case_results}

    lines.append("")
    lines.append("Top failure clusters:")

    for i, cluster in enumerate(clusters[:max_clusters], 1):
        example_result = results_by_id.get(cluster.example_case_id)
        score_detail = ""
        if example_result is not None:
            score_detail = f" [{_format_score_summary(example_result.score)}]"

        lines.append(
            f"\n{i}. [{cluster.count} cases] {cluster.category} "
            f"-- {cluster.example_description}"
        )
        lines.append(
            f"   Example: case {cluster.example_case_id}{score_detail}"
        )
        lines.append(f"   Difficulty: mostly {cluster.difficulty_range}")

    return "\n".join(lines)
