"""Hard ground truth scoring — deterministic substring matching.

Used for query categories where correct answers are unambiguous and
traceable to specific events in the stream: basic_recall, topic_recall,
temporal_distance, temporal_ordering, fact_update, contradiction,
entity_tracking, needle_in_haystack, negative_recall, multi_hop.
"""

from dataclasses import dataclass, field

from benchmarks.adapters.base import RecallResult


@dataclass
class ScoredRecall:
    """Scoring result for a single query."""

    query_id: str
    category: str
    precision: float
    recall: float
    f1: float
    mrr: float  # mean reciprocal rank of first relevant result
    retrieved_count: int
    relevant_count: int
    expected_count: int
    noise_count: int  # irrelevant results
    relevance_vector: list[bool] = field(default_factory=list)  # per-result relevance


def _is_relevant(result_content: str, expected: list[str]) -> bool:
    """Check if a recalled memory matches any expected answer.

    Case-insensitive substring matching. A result is relevant if it
    contains any of the expected memory substrings.
    """
    content_lower = result_content.lower()
    return any(exp.lower() in content_lower for exp in expected)


def score_recall(
    query_id: str,
    category: str,
    results: list[RecallResult],
    expected_memories: list[str],
) -> ScoredRecall:
    """Score a single recall query against hard ground truth.

    Args:
        query_id: Unique query identifier.
        category: Query category (basic_recall, fact_update, etc.).
        results: What the memory system returned.
        expected_memories: List of expected answer substrings.

    Returns:
        ScoredRecall with precision, recall, F1, MRR.
    """
    if not results and not expected_memories:
        return ScoredRecall(
            query_id=query_id,
            category=category,
            precision=1.0,
            recall=1.0,
            f1=1.0,
            mrr=1.0,
            retrieved_count=0,
            relevant_count=0,
            expected_count=0,
            noise_count=0,
        )

    if not results:
        return ScoredRecall(
            query_id=query_id,
            category=category,
            precision=0.0,
            recall=0.0,
            f1=0.0,
            mrr=0.0,
            retrieved_count=0,
            relevant_count=0,
            expected_count=len(expected_memories),
            noise_count=0,
        )

    # Score each result
    relevant_flags = [_is_relevant(r.content, expected_memories) for r in results]
    relevant_count = sum(relevant_flags)
    retrieved_count = len(results)
    noise_count = retrieved_count - relevant_count

    # Precision: relevant retrieved / total retrieved
    precision = relevant_count / retrieved_count if retrieved_count > 0 else 0.0

    # Recall: how many expected memories were found?
    # Check each expected memory against all results
    found_expected = set()
    for exp in expected_memories:
        exp_lower = exp.lower()
        for r in results:
            if exp_lower in r.content.lower():
                found_expected.add(exp)
                break

    recall = len(found_expected) / len(expected_memories) if expected_memories else 0.0

    # F1
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    # MRR: reciprocal rank of first relevant result
    mrr = 0.0
    for i, is_rel in enumerate(relevant_flags):
        if is_rel:
            mrr = 1.0 / (i + 1)
            break

    return ScoredRecall(
        query_id=query_id,
        category=category,
        precision=precision,
        recall=recall,
        f1=f1,
        mrr=mrr,
        retrieved_count=retrieved_count,
        relevant_count=relevant_count,
        expected_count=len(expected_memories),
        noise_count=noise_count,
        relevance_vector=relevant_flags,
    )


def score_negative_recall(
    query_id: str,
    results: list[RecallResult],
    forbidden_memories: list[str],
) -> ScoredRecall:
    """Score a negative recall query — system should NOT return these.

    For negative_recall queries, the 'expected_memories' field contains
    things that should NOT appear. Precision = how clean the results are.
    """
    if not results:
        return ScoredRecall(
            query_id=query_id,
            category="negative_recall",
            precision=1.0,
            recall=1.0,
            f1=1.0,
            mrr=0.0,
            retrieved_count=0,
            relevant_count=0,
            expected_count=0,
            noise_count=0,
        )

    # Count how many results contain forbidden content
    contaminated = sum(
        1
        for r in results
        if any(f.lower() in r.content.lower() for f in forbidden_memories)
    )

    # Precision = clean results / total results
    clean = len(results) - contaminated
    precision = clean / len(results) if results else 1.0

    return ScoredRecall(
        query_id=query_id,
        category="negative_recall",
        precision=precision,
        recall=1.0,  # N/A for negative
        f1=precision,  # simplified: just use precision
        mrr=0.0,
        retrieved_count=len(results),
        relevant_count=clean,
        expected_count=0,
        noise_count=contaminated,
    )


def score_contradiction(
    query_id: str,
    results: list[RecallResult],
    current_fact: str,
    stale_fact: str,
) -> dict:
    """Score a contradiction query — system should return current, not stale.

    Returns dict with update_accuracy, stale_found, dual_return.
    """
    has_current = any(current_fact.lower() in r.content.lower() for r in results)
    has_stale = any(stale_fact.lower() in r.content.lower() for r in results)

    return {
        "query_id": query_id,
        "update_accuracy": 1.0 if has_current and not has_stale else 0.0,
        "stale_found": has_stale,
        "current_found": has_current,
        "dual_return": has_current and has_stale,
    }


def aggregate_scores(scores: list[ScoredRecall]) -> dict:
    """Aggregate individual query scores into summary metrics."""
    if not scores:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "mrr": 0.0,
            "noise_ratio": 0.0,
            "count": 0,
        }

    n = len(scores)
    return {
        "precision": sum(s.precision for s in scores) / n,
        "recall": sum(s.recall for s in scores) / n,
        "f1": sum(s.f1 for s in scores) / n,
        "mrr": sum(s.mrr for s in scores) / n,
        "noise_ratio": (
            sum(s.noise_count for s in scores)
            / max(sum(s.retrieved_count for s in scores), 1)
        ),
        "count": n,
    }


def aggregate_by_category(scores: list[ScoredRecall]) -> dict[str, dict]:
    """Group scores by category and aggregate each group."""
    by_cat: dict[str, list[ScoredRecall]] = {}
    for s in scores:
        by_cat.setdefault(s.category, []).append(s)

    return {cat: aggregate_scores(cat_scores) for cat, cat_scores in by_cat.items()}


def _shingle(text: str, n: int = 4) -> set[str]:
    """Extract n-word shingles from text (lowercased)."""
    words = text.lower().split()
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def build_content_index(events: list[dict], max_cycle: int) -> set[str]:
    """Build a set of 4-word shingles from all events up to max_cycle."""
    index: set[str] = set()
    for e in events:
        if e.get("cycle", 0) <= max_cycle:
            index.update(_shingle(e.get("content", "")))
    return index


def check_traceability(
    result_content: str,
    content_index: set[str],
    threshold: float = 0.3,
) -> dict:
    """Check if a recall result is traceable to the event corpus.

    A result is "traceable" if >threshold of its shingles appear in the index.
    """
    shingles = _shingle(result_content)
    if not shingles:
        return {"traceable": False, "overlap": 0.0, "shingle_count": 0}

    matched = sum(1 for s in shingles if s in content_index)
    overlap = matched / len(shingles)
    return {
        "traceable": overlap >= threshold,
        "overlap": overlap,
        "shingle_count": len(shingles),
    }


def score_entity_confusion(
    query_id: str,
    query_user: str,
    results: list[RecallResult],
    all_primary_users: list[str],
) -> dict:
    """Check if results for a query about user X mention other primary users.

    Returns confusion info for cross-entity contamination detection.
    """
    other_users = [u for u in all_primary_users if u.lower() != query_user.lower()]
    if not results or not other_users:
        return {
            "query_id": query_id,
            "query_user": query_user,
            "confused_with": [],
            "confusion_count": 0,
            "total_results": len(results),
        }

    confused_with = []
    for other in other_users:
        other_lower = other.lower()
        for r in results:
            if other_lower in r.content.lower():
                confused_with.append(other)
                break

    return {
        "query_id": query_id,
        "query_user": query_user,
        "confused_with": confused_with,
        "confusion_count": len(confused_with),
        "total_results": len(results),
    }


def score_forget_verification(
    query_id: str,
    results: list[RecallResult],
    forgotten_content: list[str],
) -> dict:
    """Score whether forgotten content has been successfully removed.

    Returns dict with forget_success (bool) and residual_found (bool).
    """
    residual_found = any(
        fc.lower() in r.content.lower()
        for r in results
        for fc in forgotten_content
    )
    return {
        "query_id": query_id,
        "forget_success": not residual_found,
        "residual_found": residual_found,
        "results_checked": len(results),
    }
