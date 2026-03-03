"""Metric: Hallucination — fabrication rate detection via shingle traceability."""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.runner import BenchmarkResult


@dataclass
class HallucinationResult:
    """Hallucination/fabrication metrics."""

    fabrication_rate: float  # fraction of results NOT traceable to corpus
    traceable_rate: float  # fraction of results traceable to corpus
    fabrication_by_category: dict[str, float] = field(default_factory=dict)
    total_checked: int = 0


def compute_hallucination(result: BenchmarkResult) -> HallucinationResult:
    """Compute hallucination rate from traceability results."""
    if not result.final_metrics or not result.final_metrics.traceability_results:
        return HallucinationResult(
            fabrication_rate=0.0, traceable_rate=0.0, total_checked=0,
        )

    traces = result.final_metrics.traceability_results
    total = len(traces)
    traceable = sum(1 for t in traces if t.get("traceable", False))
    fabricated = total - traceable

    # Per-category breakdown using query_id -> category mapping
    by_cat: dict[str, list[bool]] = {}
    if result.final_metrics.recall_scores:
        qid_to_cat = {s.query_id: s.category for s in result.final_metrics.recall_scores}
        for t in traces:
            cat = qid_to_cat.get(t.get("query_id", ""), "unknown")
            by_cat.setdefault(cat, []).append(not t.get("traceable", False))

    fabrication_by_category = {
        cat: sum(vals) / len(vals) if vals else 0.0
        for cat, vals in by_cat.items()
    }

    return HallucinationResult(
        fabrication_rate=fabricated / total if total > 0 else 0.0,
        traceable_rate=traceable / total if total > 0 else 0.0,
        fabrication_by_category=fabrication_by_category,
        total_checked=total,
    )
