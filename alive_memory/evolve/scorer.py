"""Scorer — deterministic recall quality scoring with no LLM calls.

Three-level match cascade (exact -> keyword -> embedding) scores each
recalled item against ground truth facts.  Per-query scores are aggregated
into case-level and split-level results with category-specific adjustments.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import re
from typing import Any

from alive_memory.evolve.stopwords import STOPWORDS
from alive_memory.evolve.types import (
    CATEGORY_SCORING_ADJUSTMENTS,
    CaseResult,
    EvalQuery,
    RecallScore,
)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def extract_keywords(text: str) -> set[str]:
    """Lowercase, split on non-alphanumeric, remove stopwords and short tokens.

    Returns the set of meaningful tokens (length >= 3, not a stopword).
    """
    tokens = re.split(r"[^a-zA-Z0-9]+", text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in STOPWORDS}


# ---------------------------------------------------------------------------
# Match functions (three-level cascade)
# ---------------------------------------------------------------------------


def exact_match(recalled_text: str, ground_truth: str) -> bool:
    """Case-insensitive substring check."""
    return ground_truth.lower() in recalled_text.lower()


def keyword_match(
    recalled_text: str,
    ground_truth: str,
    threshold: float = 0.7,
) -> float:
    """Return overlap ratio of ground-truth keywords found in recalled text.

    A ratio >= *threshold* is typically considered a keyword match.  The raw
    ratio is returned so callers can apply their own threshold.
    """
    gt_kw = extract_keywords(ground_truth)
    recalled_kw = extract_keywords(recalled_text)
    if not gt_kw:
        return 1.0
    return len(gt_kw & recalled_kw) / len(gt_kw)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors.  Pure Python — no numpy."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def embedding_match(
    recalled_text: str,
    ground_truth: str,
    embedder: Any = None,
    threshold: float = 0.82,
) -> float:
    """Cosine similarity via an embedder.  Returns similarity score 0-1.

    If no *embedder* is provided the embedding level is skipped and ``0.0``
    is returned.  The *embedder* must be callable (sync or async) with a
    single string and return ``list[float]``.
    """
    if embedder is None:
        return 0.0
    vec_a = embedder(recalled_text)
    if inspect.isawaitable(vec_a):
        vec_a = await vec_a
    vec_b = embedder(ground_truth)
    if inspect.isawaitable(vec_b):
        vec_b = await vec_b
    return cosine_similarity(vec_a, vec_b)


async def match_fact(
    recalled_text: str,
    ground_truth: str,
    embedder: Any = None,
) -> float:
    """Three-level match cascade.

    1. **Exact match** (substring) -> ``1.0``
    2. **Keyword match** (overlap >= 0.7) -> ``0.9``
    3. **Embedding match** (cosine >= 0.82 -> ``0.8``, >= 0.65 -> ``0.5``)
    4. Otherwise -> ``0.0``
    """
    # Level 1 — exact substring
    if exact_match(recalled_text, ground_truth):
        return 1.0

    # Level 2 — keyword overlap
    kw_score = keyword_match(recalled_text, ground_truth)
    if kw_score >= 0.7:
        return 0.9

    # Level 3 — embedding similarity
    emb_score = await embedding_match(recalled_text, ground_truth, embedder=embedder)
    if emb_score >= 0.82:
        return 0.8
    if emb_score >= 0.65:
        return 0.5

    return 0.0


# ---------------------------------------------------------------------------
# Query-level scoring
# ---------------------------------------------------------------------------


def _ndcg(relevance: list[bool]) -> float:
    """Simplified nDCG with binary relevance.

    DCG  = sum(rel_i / log2(i + 2))  for i in 0..n-1
    IDCG = DCG of the ideal ranking (all relevant items first)
    """
    if not relevance:
        return 0.0

    def _dcg(rels: list[bool]) -> float:
        return sum(
            (1.0 if r else 0.0) / math.log2(i + 2) for i, r in enumerate(rels)
        )

    dcg = _dcg(relevance)
    # Ideal: all True values pushed to the front
    ideal = sorted(relevance, reverse=True)
    idcg = _dcg(ideal)
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


async def score_query(
    recalled_items: list[str],
    query: EvalQuery,
    embedder: Any = None,
) -> RecallScore:
    """Score a single recall query against ground truth.

    Metrics computed:

    * **completeness** — mean of the best ``match_fact`` score for each
      ground-truth fact across all recalled items.
    * **precision** — fraction of recalled items that matched *any*
      ground-truth fact with score >= 0.5.
    * **noise_rejection** — 1.0 minus the fraction of ``should_not_recall``
      items found (via exact match) in any recalled item.
    * **ranking_quality** — simplified nDCG over recalled items.
    * **bonus_inferences** — if found in recalled items a small bonus is
      added to completeness (capped at 1.0).  Not penalised if missing.
    * **latency_ms** — always ``0.0`` here; set externally by the runner.
    """
    if not query.ground_truth:
        return RecallScore(
            precision=1.0,
            completeness=1.0,
            noise_rejection=1.0,
            ranking_quality=1.0,
        )

    # --- completeness ---
    best_per_fact: list[float] = []
    for gt_fact in query.ground_truth:
        best = 0.0
        for item in recalled_items:
            score = await match_fact(item, gt_fact, embedder=embedder)
            if score > best:
                best = score
        best_per_fact.append(best)
    completeness = sum(best_per_fact) / len(best_per_fact) if best_per_fact else 0.0

    # --- bonus inferences ---
    if query.bonus_inferences and recalled_items:
        bonus_hits = 0
        for inference in query.bonus_inferences:
            for item in recalled_items:
                if await match_fact(item, inference, embedder=embedder) >= 0.5:
                    bonus_hits += 1
                    break
        # Small bonus: up to 0.1 for fully matched inferences
        bonus = 0.1 * (bonus_hits / len(query.bonus_inferences))
        completeness = min(completeness + bonus, 1.0)

    # --- precision ---
    if recalled_items:
        relevant_count = 0
        for item in recalled_items:
            for gt_fact in query.ground_truth:
                if await match_fact(item, gt_fact, embedder=embedder) >= 0.5:
                    relevant_count += 1
                    break
        precision = relevant_count / len(recalled_items)
    else:
        precision = 0.0

    # --- noise rejection ---
    if query.should_not_recall:
        violations = 0
        for forbidden in query.should_not_recall:
            for item in recalled_items:
                if exact_match(item, forbidden):
                    violations += 1
                    break
        noise_rejection = 1.0 - (violations / len(query.should_not_recall))
    else:
        noise_rejection = 1.0

    # --- ranking quality (nDCG) ---
    relevance: list[bool] = []
    for item in recalled_items:
        is_relevant = False
        for gt_fact in query.ground_truth:
            if await match_fact(item, gt_fact, embedder=embedder) >= 0.5:
                is_relevant = True
                break
        relevance.append(is_relevant)
    ranking_quality = _ndcg(relevance)

    return RecallScore(
        precision=precision,
        completeness=completeness,
        noise_rejection=noise_rejection,
        ranking_quality=ranking_quality,
        latency_ms=0.0,
    )


# ---------------------------------------------------------------------------
# Case-level & split-level scoring
# ---------------------------------------------------------------------------


def score_case(case_result: CaseResult) -> float:
    """Apply category-specific scoring adjustments.

    Most categories simply return ``case_result.score.composite``.
    Special categories override certain weight distributions:

    * **noise_decay** — noise_rejection weight raised to 0.35
    * **high_volume_stress** — latency penalty weight raised to 0.15
    * **contradiction_handling** — blends in a recency weight factor
    """
    s = case_result.score
    adjustments = CATEGORY_SCORING_ADJUSTMENTS.get(case_result.category, {})

    if not adjustments:
        return s.composite

    # --- noise_decay: heavier noise-rejection weight ---
    if case_result.category == "noise_decay":
        nr_weight = adjustments.get("noise_rejection_weight", 0.35)
        # Redistribute weight from default 0.20 -> nr_weight; shrink others
        remaining = 1.0 - nr_weight
        scale = remaining / 0.80  # original non-noise weight sum
        quality = (
            0.35 * scale * s.completeness
            + 0.25 * scale * s.precision
            + nr_weight * s.noise_rejection
            + 0.15 * scale * s.ranking_quality
        )
        latency_factor = min(max(s.latency_ms - 200, 0) / 800, 1.0)
        latency_penalty = 0.05 * latency_factor
        return 1.0 - quality + latency_penalty

    # --- high_volume_stress: heavier latency penalty ---
    if case_result.category == "high_volume_stress":
        lp_weight = adjustments.get("latency_penalty_weight", 0.15)
        quality = (
            0.35 * s.completeness
            + 0.25 * s.precision
            + 0.20 * s.noise_rejection
            + 0.15 * s.ranking_quality
        )
        latency_factor = min(max(s.latency_ms - 200, 0) / 800, 1.0)
        latency_penalty = lp_weight * latency_factor
        return 1.0 - quality + latency_penalty

    # --- contradiction_handling: blend in recency weight ---
    if case_result.category == "contradiction_handling":
        recency_w = adjustments.get("recency_weight", 0.3)
        base = s.composite
        # Ranking quality proxies recency: relevant (recent) items first
        recency_bonus = recency_w * s.ranking_quality
        return base - recency_bonus

    # Fallback for categories with adjustments we don't special-case yet
    return s.composite


def aggregate_split(results: list[CaseResult]) -> float:
    """Mean of ``score_case()`` for all results.

    Returns ``1.0`` (worst possible) when *results* is empty.
    Lower is better.
    """
    if not results:
        return 1.0
    return sum(score_case(cr) for cr in results) / len(results)
