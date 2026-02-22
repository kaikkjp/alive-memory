"""sim.metrics.memory_score — N3: Memory & Relationship Score.

Evaluates returning visitor (Tier 3) interactions on four dimensions:
1. Identity recall — did the Shopkeeper recognize/reference the visitor?
2. Transaction recall — did the Shopkeeper reference prior purchase/sale?
3. Preference continuity — consistent taste/recommendations (0-1)
4. Relationship progression — conversation depth increase vs first visit

Usage:
    from sim.metrics.memory_score import MemoryScorer
    scorer = MemoryScorer()
    scorer.record_visit(visitor_id, visit_data)
    n3 = scorer.compute_n3()
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Multi-word phrases that reliably indicate recognition of a returning visitor.
# Single words like "back" or "again" fire too often in normal dialogue.
_RECOGNITION_PHRASES = [
    "welcome back", "good to see you", "you were here",
    "came by", "last time", "remember you",
    "you again", "back again", "returned", "returning",
    "recognize you", "seen you before", "visited before",
    "you came", "you visited",
]

# Patterns that indicate recall of a *past* transaction, not current sales talk.
# Bare words like "price" or "deal" fire on normal negotiation dialogue.
_TRANSACTION_PHRASES = [
    "bought", "purchased", "you sold", "we traded",
    "last purchase", "that card", "last time",
    "previous", "before you", "you had",
    "you picked up", "you chose", "your order",
]


@dataclass
class VisitRecord:
    """Record of a single visit for memory scoring."""
    visitor_id: str
    visitor_name: str
    visit_number: int  # 1-indexed (1 = first, 2 = first return, etc.)
    is_return: bool
    goal: str
    turn_count: int
    shopkeeper_dialogues: list[str] = field(default_factory=list)
    visitor_dialogues: list[str] = field(default_factory=list)
    memory_stub: str | None = None
    exit_reason: str = ""
    # Scoring signals
    identity_recalled: bool = False
    transaction_recalled: bool = False


class MemoryScorer:
    """Computes N3: Memory & Relationship Score for Tier 3 visitors.

    Tracks all visits per visitor and scores return visits on
    identity recall, transaction recall, preference continuity,
    and relationship depth progression.
    """

    def __init__(self):
        self._visits: dict[str, list[VisitRecord]] = {}

    def record_visit(
        self,
        visitor_id: str,
        visitor_name: str,
        is_return: bool,
        goal: str,
        turn_count: int,
        shopkeeper_dialogues: list[str] | None = None,
        visitor_dialogues: list[str] | None = None,
        memory_stub: str | None = None,
        exit_reason: str = "",
    ):
        """Record a completed visit for later scoring.

        Args:
            visitor_id: Stable visitor ID across visits.
            visitor_name: Display name of the visitor.
            is_return: Whether this is a return visit (Tier 3).
            goal: Visitor's goal for this visit.
            turn_count: Number of dialogue turns.
            shopkeeper_dialogues: List of shopkeeper's dialogue lines.
            visitor_dialogues: List of visitor's dialogue lines.
            memory_stub: Memory context from prior visit (Tier 3).
            exit_reason: Why the visitor left.
        """
        if visitor_id not in self._visits:
            self._visits[visitor_id] = []

        visit_number = len(self._visits[visitor_id]) + 1
        sk_dialogues = shopkeeper_dialogues or []

        record = VisitRecord(
            visitor_id=visitor_id,
            visitor_name=visitor_name,
            visit_number=visit_number,
            is_return=is_return,
            goal=goal,
            turn_count=turn_count,
            shopkeeper_dialogues=sk_dialogues,
            visitor_dialogues=visitor_dialogues or [],
            memory_stub=memory_stub,
            exit_reason=exit_reason,
        )

        # Score recognition signals from shopkeeper dialogue
        if is_return and sk_dialogues:
            combined = " ".join(sk_dialogues).lower()
            record.identity_recalled = self._check_identity_recall(
                combined, visitor_name,
            )
            record.transaction_recalled = self._check_transaction_recall(
                combined,
            )

        self._visits[visitor_id].append(record)

    def compute_n3(self) -> dict:
        """Compute aggregate N3: Memory & Relationship Score.

        Returns:
            Dictionary with:
            - identity_recall_rate: fraction of return visits where
              shopkeeper recognized the visitor
            - transaction_recall_rate: fraction of return visits where
              shopkeeper referenced prior transactions
            - preference_continuity: goal consistency across visits (0-1)
            - depth_gradient: average depth change from first to return visit
            - total_return_visits: count of scored return visits
            - total_returning_visitors: count of visitors who returned
        """
        return_visits: list[VisitRecord] = []
        returning_visitors: set[str] = set()

        for vid, visits in self._visits.items():
            for v in visits:
                if v.is_return:
                    return_visits.append(v)
                    returning_visitors.add(vid)

        if not return_visits:
            return {
                "identity_recall_rate": 0.0,
                "transaction_recall_rate": 0.0,
                "preference_continuity": 0.0,
                "depth_gradient": 0.0,
                "total_return_visits": 0,
                "total_returning_visitors": 0,
            }

        # N3a: Identity recall rate
        identity_hits = sum(1 for v in return_visits if v.identity_recalled)
        identity_recall = identity_hits / len(return_visits)

        # N3b: Transaction recall rate
        tx_hits = sum(1 for v in return_visits if v.transaction_recalled)
        tx_recall = tx_hits / len(return_visits)

        # N3c: Preference continuity — goal consistency across visits
        continuity_scores: list[float] = []
        for vid in returning_visitors:
            visits = self._visits[vid]
            if len(visits) < 2:
                continue
            goals = [v.goal for v in visits]
            # Fraction of visits with same goal as first visit
            first_goal = goals[0]
            same = sum(1 for g in goals[1:] if g == first_goal)
            continuity_scores.append(same / len(goals[1:]))
        preference_continuity = (
            sum(continuity_scores) / len(continuity_scores)
            if continuity_scores else 0.0
        )

        # N3d: Depth gradient — per-visitor average depth ratio,
        # then averaged across visitors (consistent with preference_continuity)
        visitor_gradients: list[float] = []
        for vid in returning_visitors:
            visits = self._visits[vid]
            first = next((v for v in visits if not v.is_return), None)
            returns = [v for v in visits if v.is_return]
            if first and returns and first.turn_count > 0:
                ratios = [rv.turn_count / first.turn_count for rv in returns]
                visitor_gradients.append(sum(ratios) / len(ratios))
        depth_gradient = (
            sum(visitor_gradients) / len(visitor_gradients)
            if visitor_gradients else 0.0
        )

        return {
            "identity_recall_rate": round(identity_recall, 3),
            "transaction_recall_rate": round(tx_recall, 3),
            "preference_continuity": round(preference_continuity, 3),
            "depth_gradient": round(depth_gradient, 3),
            "total_return_visits": len(return_visits),
            "total_returning_visitors": len(returning_visitors),
        }

    @property
    def visit_count(self) -> int:
        """Total number of recorded visits across all visitors."""
        return sum(len(v) for v in self._visits.values())

    @property
    def returning_visitor_ids(self) -> set[str]:
        """Set of visitor IDs that have at least one return visit."""
        result: set[str] = set()
        for vid, visits in self._visits.items():
            if any(v.is_return for v in visits):
                result.add(vid)
        return result

    @staticmethod
    def _check_identity_recall(text: str, visitor_name: str) -> bool:
        """Check if shopkeeper dialogue contains recognition signals.

        Uses multi-word phrases to avoid false positives from common
        words like 'back' or 'again' in normal dialogue.
        """
        # Check for name mention
        if visitor_name.lower() in text:
            return True
        # Check recognition phrases (multi-word, low false-positive)
        for phrase in _RECOGNITION_PHRASES:
            if phrase in text:
                return True
        return False

    @staticmethod
    def _check_transaction_recall(text: str) -> bool:
        """Check if shopkeeper dialogue references prior transactions.

        Uses past-tense and contextual phrases to avoid false positives
        from current-visit sales talk like 'price' or 'deal'.
        """
        for phrase in _TRANSACTION_PHRASES:
            if phrase in text:
                return True
        return False
