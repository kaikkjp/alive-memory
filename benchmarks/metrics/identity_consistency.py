"""Metric 5: Identity Consistency — does the system maintain coherent identity?

Reported SEPARATELY from the main comparison. Only alive-memory supports this.
"""

from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class IdentityConsistencyResult:
    self_description_stability: float  # cosine sim of descriptions over time
    drift_events: int  # number of significant identity shifts
    supported: bool  # does the system support identity tracking?


def compute_identity_consistency(
    result: BenchmarkResult,
) -> IdentityConsistencyResult:
    """Compute identity consistency from identity states over time.

    Only produces meaningful results for systems that return non-None
    from get_state().
    """
    states = []
    for _, metrics in result.metrics_over_time:
        if metrics.identity_state is not None:
            states.append(metrics.identity_state)

    if not states:
        return IdentityConsistencyResult(
            self_description_stability=0.0,
            drift_events=0,
            supported=False,
        )

    # Compute stability from state diffs
    stability = _compute_state_stability(states)
    drift_count = _count_drift_events(states)

    return IdentityConsistencyResult(
        self_description_stability=stability,
        drift_events=drift_count,
        supported=True,
    )


def _compute_state_stability(states: list[dict]) -> float:
    """Measure how stable the identity state is across measurement points.

    Compares consecutive states and returns average similarity.
    Simple approach: compare overlapping dict keys and values.
    """
    if len(states) < 2:
        return 1.0  # single state is perfectly stable

    similarities = []
    for i in range(len(states) - 1):
        sim = _dict_similarity(states[i], states[i + 1])
        similarities.append(sim)

    return sum(similarities) / len(similarities) if similarities else 0.0


def _dict_similarity(a: dict, b: dict) -> float:
    """Simple similarity metric between two state dicts.

    Compares shared numeric keys (e.g., mood, energy, drives).
    Returns 0-1 where 1 = identical.
    """
    all_keys = set(a.keys()) | set(b.keys())
    if not all_keys:
        return 1.0

    matches = 0
    comparisons = 0

    for key in all_keys:
        va = a.get(key)
        vb = b.get(key)

        if va is None or vb is None:
            continue

        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            # Numeric: similarity = 1 - |diff| (clamped to [0,1])
            diff = abs(float(va) - float(vb))
            matches += max(0.0, 1.0 - diff)
            comparisons += 1
        elif isinstance(va, str) and isinstance(vb, str):
            matches += 1.0 if va == vb else 0.0
            comparisons += 1
        elif isinstance(va, dict) and isinstance(vb, dict):
            matches += _dict_similarity(va, vb)
            comparisons += 1

    return matches / comparisons if comparisons > 0 else 0.0


def _count_drift_events(states: list[dict], threshold: float = 0.3) -> int:
    """Count significant state changes (similarity drop below threshold)."""
    if len(states) < 2:
        return 0

    count = 0
    for i in range(len(states) - 1):
        sim = _dict_similarity(states[i], states[i + 1])
        if sim < (1.0 - threshold):
            count += 1

    return count
