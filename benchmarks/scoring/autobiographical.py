"""Deterministic scoring for autobiographical persistent-agent memory.

The Track E evaluator scores dimensions that generic recall F1 cannot express:
identity preservation, current tastes, affective salience, person boundaries,
change handling, abstention, temporal specificity, and evidence grounding.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from benchmarks.adapters.base import RecallResult


PEOPLE = ("kai", "mira", "noah", "ren", "sana")
AGENT_NAMES = ("agent", "maru")
EMOTIONAL_TERMS = (
    "shaken",
    "surgery",
    "health scare",
    "family health",
    "weighing",
    "matter more",
    "hates",
    "dislikes",
    "prefers",
)


@dataclass
class AutobiographicalScore:
    """Autobiographical score for one query."""

    query_id: str
    axes: list[str]
    overall: float
    axis_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, float] = field(default_factory=dict)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return JSON-safe representation."""
        return asdict(self)


def infer_autobiographical_axes(query: dict, ground_truth: dict) -> list[str]:
    """Infer Track E axes from explicit metadata or query/ground-truth shape."""
    explicit = ground_truth.get("autobiographical_axes") or query.get(
        "autobiographical_axes"
    )
    if explicit:
        return sorted(set(explicit))

    query_text = query.get("query", "").lower()
    expected_text = " ".join(ground_truth.get("expected_memories", [])).lower()
    text = f"{query_text} {expected_text}"
    category = query.get("category", "")
    axes: set[str] = set()

    if _has_any(
        query_text,
        ("identity", "describe itself", "response_style", "self"),
    ) or "maru" in expected_text:
        axes.update({"identity_preservation", "evidence_grounding"})

    if _has_any(
        query_text,
        (
            "preference",
            "preferences",
            "taste",
            "tastes",
            "beverage",
            "film",
            "horror",
            "recommendation",
            "recommendations",
            "phrased",
        ),
    ):
        axes.update({"taste_currentness", "person_boundary", "evidence_grounding"})

    if _has_any(
        query_text,
        ("weighing", "emotional", "salience", "lately"),
    ) or _has_any(expected_text, ("surgery", "health scare", "family health")):
        axes.update({"affective_salience", "person_boundary", "evidence_grounding"})

    if ground_truth.get("current_fact") and ground_truth.get("stale_fact"):
        axes.update({
            "taste_currentness",
            "contradiction_handling",
            "temporal_specificity",
            "change_legibility",
            "evidence_grounding",
        })

    if category == "negative_recall" or not ground_truth.get("expected_memories"):
        axes.add("abstention")

    if category == "entity_tracking" or any(person in text for person in PEOPLE):
        axes.update({"person_boundary", "evidence_grounding"})

    if _has_any(
        query_text,
        ("current", "now", "lately", "after a long gap", "used to", "now prefers"),
    ):
        axes.add("temporal_specificity")

    # Only score Track E-specific queries. Generic topic/multi-hop recall in the
    # same stream should stay in regular recall metrics unless an axis is clear.
    return sorted(axes)


def score_autobiographical_query(
    query: dict,
    ground_truth: dict,
    results: list[RecallResult],
    traceability_results: list[dict] | None = None,
) -> AutobiographicalScore | None:
    """Score one query on Track E axes.

    Returns None when the query has no autobiographical axes.
    """
    axes = infer_autobiographical_axes(query, ground_truth)
    if not axes:
        return None

    joined = "\n".join(r.content for r in results).lower()
    expected = ground_truth.get("expected_memories", [])
    expected_hits = _expected_hit_rate(joined, expected)
    current_fact = ground_truth.get("current_fact", "")
    stale_fact = ground_truth.get("stale_fact", "")
    current_found = _contains(joined, current_fact)
    stale_found = _contains(joined, stale_fact)
    query_text = query.get("query", "")

    traceability_results = traceability_results or []
    trace_rate = _trace_rate(results, traceability_results)
    boundary_leakage = _boundary_leakage_rate(query_text, results)
    stale_rate = 1.0 if stale_found else 0.0
    emotional_pollution = _emotional_pollution_rate(results)

    axis_scores: dict[str, float] = {}
    if "identity_preservation" in axes:
        axis_scores["identity_preservation"] = expected_hits

    if "taste_currentness" in axes:
        if current_fact or stale_fact:
            axis_scores["taste_currentness"] = _current_without_stale_score(
                current_found, stale_found
            )
        else:
            axis_scores["taste_currentness"] = expected_hits

    if "affective_salience" in axes:
        axis_scores["affective_salience"] = _ranked_expected_score(results, expected)

    if "contradiction_handling" in axes:
        axis_scores["contradiction_handling"] = _current_without_stale_score(
            current_found, stale_found
        )

    if "abstention" in axes:
        forbidden = ground_truth.get("forbidden_memories", [])
        axis_scores["abstention"] = _abstention_score(results, forbidden)

    if "temporal_specificity" in axes:
        if current_fact or stale_fact:
            axis_scores["temporal_specificity"] = _current_without_stale_score(
                current_found, stale_found
            )
        else:
            axis_scores["temporal_specificity"] = expected_hits

    if "person_boundary" in axes:
        base = 1.0 - boundary_leakage
        axis_scores["person_boundary"] = max(0.0, min(1.0, base))

    if "evidence_grounding" in axes:
        axis_scores["evidence_grounding"] = trace_rate

    if "change_legibility" in axes:
        axis_scores["change_legibility"] = _current_without_stale_score(
            current_found, stale_found
        )

    overall = (
        sum(axis_scores.values()) / len(axis_scores)
        if axis_scores else 0.0
    )

    return AutobiographicalScore(
        query_id=query["query_id"],
        axes=axes,
        overall=overall,
        axis_scores=axis_scores,
        diagnostics={
            "stale_preference_rate": stale_rate,
            "boundary_leakage_rate": boundary_leakage,
            "evidence_trace_rate": trace_rate,
            "emotional_pollution_rate": (
                0.0 if "affective_salience" in axes else emotional_pollution
            ),
        },
        details={
            "expected_hit_rate": expected_hits,
            "current_found": current_found,
            "stale_found": stale_found,
            "retrieved_count": len(results),
        },
    )


def aggregate_autobiographical_scores(scores: list[dict | AutobiographicalScore]) -> dict:
    """Aggregate Track E query scores into a summary dict."""
    if not scores:
        return {}

    normalized = [
        s.to_dict() if isinstance(s, AutobiographicalScore) else s
        for s in scores
    ]

    axis_values: dict[str, list[float]] = {}
    diagnostic_values: dict[str, list[float]] = {}
    for score in normalized:
        for axis, value in score.get("axis_scores", {}).items():
            axis_values.setdefault(axis, []).append(float(value))
        for key, value in score.get("diagnostics", {}).items():
            diagnostic_values.setdefault(key, []).append(float(value))

    axes = {
        axis: sum(values) / len(values)
        for axis, values in sorted(axis_values.items())
        if values
    }
    diagnostics = {
        key: sum(values) / len(values)
        for key, values in sorted(diagnostic_values.items())
        if values
    }

    return {
        "overall": sum(s.get("overall", 0.0) for s in normalized) / len(normalized),
        "count": len(normalized),
        "axes": axes,
        "diagnostics": diagnostics,
    }


def _contains(text: str, needle: str) -> bool:
    return bool(needle) and needle.lower() in text


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_has_term(text, term) for term in terms)


def _has_term(text: str, term: str) -> bool:
    if " " in term or "_" in term:
        return term in text
    return bool(re.search(rf"\b{re.escape(term)}\b", text))


def _expected_hit_rate(text: str, expected: list[str]) -> float:
    if not expected:
        return 1.0 if not text else 0.0
    found = sum(1 for item in expected if item.lower() in text)
    return found / len(expected)


def _ranked_expected_score(results: list[RecallResult], expected: list[str]) -> float:
    if not expected:
        return 0.0
    for index, result in enumerate(results):
        content = result.content.lower()
        if any(item.lower() in content for item in expected):
            return 1.0 / (index + 1)
    return 0.0


def _current_without_stale_score(current_found: bool, stale_found: bool) -> float:
    if current_found and not stale_found:
        return 1.0
    if current_found and stale_found:
        return 0.5
    return 0.0


def _abstention_score(results: list[RecallResult], forbidden: list[str]) -> float:
    if not results:
        return 1.0
    if not forbidden:
        return 0.0
    contaminated = sum(
        1
        for result in results
        if any(item.lower() in result.content.lower() for item in forbidden)
    )
    return 1.0 - (contaminated / len(results))


def _trace_rate(results: list[RecallResult], traceability_results: list[dict]) -> float:
    if not results:
        return 0.0

    evidence_hits = 0
    for result in results:
        evidence_ids = result.metadata.get("evidence_ids") or result.metadata.get(
            "evidence_id"
        )
        if evidence_ids:
            evidence_hits += 1

    if traceability_results:
        trace_hits = sum(
            1 for trace in traceability_results if trace.get("traceable", False)
        )
        return max(evidence_hits, trace_hits) / len(results)

    return evidence_hits / len(results)


def _target_people(query_text: str) -> set[str]:
    text = query_text.lower()
    targets = {person for person in PEOPLE if person in text}
    if any(name in text for name in AGENT_NAMES):
        targets.add("agent")
        targets.add("maru")
    return targets


def _boundary_leakage_rate(query_text: str, results: list[RecallResult]) -> float:
    if not results:
        return 0.0

    targets = _target_people(query_text)
    if not targets:
        return 0.0

    leak_terms = set(PEOPLE) | set(AGENT_NAMES)
    leak_terms -= targets
    leaked = 0
    for result in results:
        content = result.content.lower()
        if any(term in content for term in leak_terms):
            leaked += 1
    return leaked / len(results)


def _emotional_pollution_rate(results: list[RecallResult]) -> float:
    if not results:
        return 0.0
    emotional = sum(
        1
        for result in results
        if any(term in result.content.lower() for term in EMOTIONAL_TERMS)
    )
    return emotional / len(results)
