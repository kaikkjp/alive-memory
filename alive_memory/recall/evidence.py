"""Evidence ranking with recency and contradiction handling."""

from __future__ import annotations

from alive_memory.types import EvidenceBlock


def rank_with_recency(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    """Re-rank evidence blocks: trust_rank first, then newest first at same level."""
    return sorted(
        blocks,
        key=lambda eb: (eb.trust_rank, -_timestamp_score(eb.timestamp), -eb.score),
    )


def compute_confidence(blocks: list[EvidenceBlock], total_hits: int) -> tuple[float, bool]:
    """Compute confidence and abstention recommendation.

    Returns (confidence, abstain_recommended).
    """
    has_raw = any(eb.source_type == "raw_turn" for eb in blocks)
    has_strong_raw = any(
        eb.source_type == "raw_turn" and eb.score > 0.5 for eb in blocks
    )
    has_facts = any(eb.source_type in ("totem", "trait") for eb in blocks)

    if has_raw and has_strong_raw:
        return 0.9, False
    if has_raw or has_facts:
        return 0.6, False
    if total_hits > 0:
        return 0.3, False
    return 0.1, True


def _timestamp_score(ts: str) -> float:
    """Convert ISO timestamp to a float for sorting (higher = more recent)."""
    if not ts:
        return 0.0
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        return dt.timestamp()
    except Exception:
        return 0.0
