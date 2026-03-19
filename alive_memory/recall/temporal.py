"""Parse temporal hints from queries and filter/rerank candidates."""

from __future__ import annotations

import re

_TEMPORAL_PATTERNS: dict[str, str] = {
    "before": r"\bbefore\b",
    "after": r"\bafter\b",
    "when": r"\bwhen\b",
    "first": r"\bfirst\b",
    "latest": r"\b(?:latest|most recent)\b",
    "last_week": r"\blast week\b",
    "yesterday": r"\byesterday\b",
}


def detect_temporal_hints(query: str) -> dict[str, bool]:
    """Detect temporal operators in the query text."""
    hints: dict[str, bool] = {}
    q_lower = query.lower()
    for key, pattern in _TEMPORAL_PATTERNS.items():
        if re.search(pattern, q_lower):
            hints[key] = True
    return hints


def apply_temporal_sort(
    results: list[dict],
    hints: dict[str, bool],
) -> list[dict]:
    """Reorder results based on temporal hints.

    'first' → oldest first; 'latest' → newest first.
    """
    if not hints:
        return results

    if hints.get("first"):
        results.sort(key=lambda r: r.get("created_at") or "")
    elif hints.get("latest"):
        results.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    return results
