"""Metric: Dream Evaluation — consolidation output quality (alive-only)."""

from __future__ import annotations

from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult


@dataclass
class DreamEvaluationResult:
    """Consolidation output quality metrics."""

    coherence: float  # 0-1 composite score
    relevance: float  # lexical diversity as proxy
    dream_count: int
    reflection_count: int
    method: str  # "heuristic" or "llm"
    supported: bool


def _length_score(text: str) -> float:
    """Score based on length: >20 words = 1.0, scales linearly."""
    words = text.split()
    if len(words) >= 20:
        return 1.0
    return len(words) / 20.0


def _lexical_diversity(text: str) -> float:
    """Ratio of unique words to total words."""
    words = text.lower().split()
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _repetition_penalty(text: str) -> float:
    """Detect repeated 3-grams. Returns penalty 0-1 (0 = no repetition)."""
    words = text.lower().split()
    if len(words) < 3:
        return 0.0

    trigrams = [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
    unique = len(set(trigrams))
    total = len(trigrams)

    if total == 0:
        return 0.0
    repetition_rate = 1.0 - (unique / total)
    return repetition_rate


def _score_text(text: str) -> tuple[float, float]:
    """Score a single consolidation output. Returns (coherence, relevance)."""
    length = _length_score(text)
    diversity = _lexical_diversity(text)
    penalty = _repetition_penalty(text)

    coherence = max(0.0, length * (1.0 - penalty))
    relevance = diversity

    return coherence, relevance


def compute_dream_evaluation(result: BenchmarkResult) -> DreamEvaluationResult:
    """Evaluate quality of consolidation outputs using heuristics."""
    if not result.final_metrics:
        return DreamEvaluationResult(
            coherence=0.0, relevance=0.0, dream_count=0,
            reflection_count=0, method="heuristic", supported=False,
        )

    adapter_data = result.final_metrics.adapter_data
    reports = adapter_data.get("consolidation_reports", [])
    total_dreams = adapter_data.get("total_dreams", 0)
    total_reflections = adapter_data.get("total_reflections", 0)

    if not reports:
        return DreamEvaluationResult(
            coherence=0.0, relevance=0.0,
            dream_count=total_dreams, reflection_count=total_reflections,
            method="heuristic", supported=False,
        )

    # Score all dreams and reflections
    all_coherence = []
    all_relevance = []

    for report in reports:
        for dream in report.get("dreams", []):
            c, r = _score_text(dream)
            all_coherence.append(c)
            all_relevance.append(r)
        for ref in report.get("reflections", []):
            c, r = _score_text(ref)
            all_coherence.append(c)
            all_relevance.append(r)

    if not all_coherence:
        return DreamEvaluationResult(
            coherence=0.0, relevance=0.0,
            dream_count=total_dreams, reflection_count=total_reflections,
            method="heuristic", supported=False,
        )

    return DreamEvaluationResult(
        coherence=sum(all_coherence) / len(all_coherence),
        relevance=sum(all_relevance) / len(all_relevance),
        dream_count=total_dreams,
        reflection_count=total_reflections,
        method="heuristic",
        supported=True,
    )
