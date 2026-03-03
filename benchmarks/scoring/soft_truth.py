"""Soft ground truth scoring — LLM-as-judge evaluation.

Used for query categories where correct answers require judgment:
pattern_recognition, emotional_context.

Uses 3 independent LLM judges, majority vote, and reports
inter-rater agreement via Fleiss' kappa.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]


JUDGE_MODEL = "claude-haiku-4-5-20251001"
NUM_JUDGES = 3

JUDGE_PROMPT = """\
You are evaluating whether a memory system's recall result is relevant to a query.

Query: {query}
Expected answer should relate to: {expected_description}

Retrieved memory:
---
{retrieved_content}
---

Is this retrieved memory relevant to answering the query?
Consider: does it contain information that would help answer the query correctly?

Reply with exactly one word: RELEVANT or IRRELEVANT"""


@dataclass
class JudgeVote:
    """A single judge's assessment."""

    judge_id: int
    relevant: bool
    raw_response: str


@dataclass
class SoftScoredRecall:
    """Soft-scored result for a single query."""

    query_id: str
    category: str
    precision: float
    recall: float
    f1: float
    agreement: float  # Fleiss' kappa across judges
    votes_per_result: list[list[JudgeVote]]


def fleiss_kappa(ratings: list[list[int]], n_categories: int = 2) -> float:
    """Compute Fleiss' kappa for inter-rater agreement.

    Args:
        ratings: List of items, each item is a list of category assignments
                 (one per rater). E.g., [[0,1,1], [1,1,1], [0,0,1]]
        n_categories: Number of categories (default 2: relevant/irrelevant).

    Returns:
        Kappa coefficient (-1 to 1). 1 = perfect agreement, 0 = chance.
    """
    if not ratings:
        return 0.0

    n_items = len(ratings)
    n_raters = len(ratings[0]) if ratings else 0

    if n_raters < 2 or n_items < 1:
        return 0.0

    # Count category assignments per item
    counts = []
    for item_ratings in ratings:
        cat_counts = [0] * n_categories
        for r in item_ratings:
            cat_counts[r] += 1
        counts.append(cat_counts)

    # P_i: agreement for each item
    p_items = []
    for cat_counts in counts:
        p_i = sum(c * (c - 1) for c in cat_counts) / (n_raters * (n_raters - 1))
        p_items.append(p_i)

    p_bar = sum(p_items) / n_items  # mean observed agreement

    # P_e: expected agreement by chance
    p_cats = []
    for j in range(n_categories):
        p_j = sum(counts[i][j] for i in range(n_items)) / (n_items * n_raters)
        p_cats.append(p_j)
    p_e = sum(p ** 2 for p in p_cats)

    if abs(1.0 - p_e) < 1e-10:
        return 1.0  # perfect agreement

    return (p_bar - p_e) / (1.0 - p_e)


async def _judge_relevance(
    client: "anthropic.AsyncAnthropic",
    judge_id: int,
    query: str,
    expected_description: str,
    retrieved_content: str,
) -> JudgeVote:
    """Ask one LLM judge whether a result is relevant."""
    prompt = JUDGE_PROMPT.format(
        query=query,
        expected_description=expected_description,
        retrieved_content=retrieved_content,
    )

    try:
        resp = await client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=10,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip().upper()
        relevant = "RELEVANT" in raw
    except Exception as e:
        raw = f"ERROR: {e}"
        relevant = False

    return JudgeVote(judge_id=judge_id, relevant=relevant, raw_response=raw)


async def score_soft_recall(
    query_id: str,
    category: str,
    query: str,
    expected_description: str,
    results: list,
    expected_count: int,
    api_key: Optional[str] = None,
) -> SoftScoredRecall:
    """Score a recall query using LLM-as-judge.

    Args:
        query_id: Unique query identifier.
        category: Query category (pattern_recognition, emotional_context).
        query: The recall query text.
        expected_description: Natural language description of what a good answer contains.
        results: RecallResult list from the adapter.
        expected_count: How many relevant results we'd expect.
        api_key: Anthropic API key. Uses ANTHROPIC_API_KEY env var if not provided.
    """
    if anthropic is None:
        raise ImportError("anthropic package required for soft truth scoring")

    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    client = anthropic.AsyncAnthropic(**kwargs)

    votes_per_result: list[list[JudgeVote]] = []

    for result in results:
        # Run all judges in parallel for this result
        tasks = [
            _judge_relevance(
                client, j, query, expected_description, result.content
            )
            for j in range(NUM_JUDGES)
        ]
        votes = await asyncio.gather(*tasks)
        votes_per_result.append(list(votes))

    # Majority vote per result
    relevant_flags = []
    for votes in votes_per_result:
        yes_count = sum(1 for v in votes if v.relevant)
        relevant_flags.append(yes_count > NUM_JUDGES // 2)

    relevant_count = sum(relevant_flags)
    retrieved_count = len(results)

    precision = relevant_count / retrieved_count if retrieved_count > 0 else 0.0
    recall = min(relevant_count / expected_count, 1.0) if expected_count > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    # Fleiss' kappa across all results
    if votes_per_result:
        ratings = [
            [1 if v.relevant else 0 for v in votes] for votes in votes_per_result
        ]
        agreement = fleiss_kappa(ratings)
    else:
        agreement = 0.0

    return SoftScoredRecall(
        query_id=query_id,
        category=category,
        precision=precision,
        recall=recall,
        f1=f1,
        agreement=agreement,
        votes_per_result=votes_per_result,
    )
