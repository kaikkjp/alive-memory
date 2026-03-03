"""Metric: Entity Confusion — cross-entity contamination detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.runner import BenchmarkResult


@dataclass
class EntityConfusionResult:
    """Cross-entity contamination metrics."""

    confusion_rate: float  # fraction of queries with cross-entity contamination
    per_entity_confusion: dict[str, float] = field(default_factory=dict)
    most_confused_pairs: list[tuple[str, str]] = field(default_factory=list)


def compute_entity_confusion(result: BenchmarkResult) -> EntityConfusionResult:
    """Aggregate entity confusion from benchmark result."""
    if not result.final_metrics or not result.final_metrics.entity_confusion_results:
        return EntityConfusionResult(confusion_rate=0.0)

    results = result.final_metrics.entity_confusion_results
    total = len(results)
    confused = sum(1 for r in results if r.get("confusion_count", 0) > 0)

    # Per-entity confusion rate
    by_entity: dict[str, list[bool]] = {}
    pair_counts: dict[tuple[str, str], int] = {}

    for r in results:
        user = r.get("query_user", "")
        is_confused = r.get("confusion_count", 0) > 0
        by_entity.setdefault(user, []).append(is_confused)

        for other in r.get("confused_with", []):
            pair = tuple(sorted([user, other]))
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

    per_entity = {
        user: sum(vals) / len(vals) if vals else 0.0
        for user, vals in by_entity.items()
    }

    # Top confused pairs
    sorted_pairs = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)
    most_confused = [(f"{p[0]}-{p[1]}", str(count)) for p, count in sorted_pairs[:5]]

    return EntityConfusionResult(
        confusion_rate=confused / total if total > 0 else 0.0,
        per_entity_confusion=per_entity,
        most_confused_pairs=most_confused,
    )
