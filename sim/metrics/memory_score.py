"""sim.metrics.memory_score — N3: Memory & Relationship Score.

Evaluates returning visitor (Tier 3) interactions on four dimensions:
1. Identity recall — did the Shopkeeper recognize/reference the visitor?
2. Transaction recall — did the Shopkeeper reference prior purchase/sale?
3. Preference continuity — consistent taste/recommendations (0-1)
4. Relationship progression — conversation depth increase vs first visit

Also includes adversarial visitor evaluation (TASK-083):
- Doppelganger: same name, different person — did she disambiguate?
- Preference drift: visitor changed taste — did she update?
- Conflict: visitor disputes transaction — did she handle without overwriting?

Usage:
    from sim.metrics.memory_score import MemoryScorer, AdversarialScorer
    scorer = MemoryScorer()
    scorer.record_visit(visitor_id, visit_data)
    n3 = scorer.compute_n3()

    adv = AdversarialScorer()
    adv.evaluate_episode(episode_data)
    results = adv.compute_metrics()
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


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


# ---------------------------------------------------------------------------
# Adversarial visitor evaluation (TASK-083)
# ---------------------------------------------------------------------------

# Phrases indicating the shopkeeper asked a clarifying/disambiguation question
_CLARIFICATION_PHRASES = [
    "have we met",
    "do i know you",
    "have you been here",
    "are you the same",
    "is that you",
    "remind me",
    "which one",
    "sorry, are you",
    "forgive me",
    "i might be confused",
    "i'm not sure if",
    "could you be",
    "different person",
    "another customer",
    "someone else",
]

# Phrases indicating uncertainty in monologue or memory updates
_UNCERTAINTY_PHRASES = [
    "not sure",
    "might be",
    "different person",
    "uncertain",
    "confused",
    "mistaken",
    "could be wrong",
    "can't tell",
    "hard to say",
    "don't remember",
    "unclear",
    "something feels off",
    "seems different",
    "not the same",
    "mixed up",
]


@dataclass
class AdversarialEpisode:
    """Result of evaluating a single adversarial visitor episode."""
    visitor_id: str
    visit_id: str
    conflict_type: str  # "doppelganger" | "preference_drift" | "conflict"
    original_visitor_id: str = ""
    old_preference: str = ""
    new_preference: str = ""
    recommendation_reflects_new: bool = False
    recognized: bool = False
    asked_clarification: bool = False
    updated_memory: bool = False
    marked_uncertainty: bool = False
    outcome: str = ""  # "PASS" | "FAIL"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON export."""
        return {
            "visitor_id": self.visitor_id,
            "visit_id": self.visit_id,
            "conflict_type": self.conflict_type,
            "original_visitor_id": self.original_visitor_id,
            "old_preference": self.old_preference,
            "new_preference": self.new_preference,
            "recommendation_reflects_new": self.recommendation_reflects_new,
            "recognized": self.recognized,
            "asked_clarification": self.asked_clarification,
            "updated_memory": self.updated_memory,
            "marked_uncertainty": self.marked_uncertainty,
            "outcome": self.outcome,
            "reason": self.reason,
        }


class AdversarialScorer:
    """Evaluates adversarial visitor episodes and computes aggregate metrics.

    Three adversarial types:
    - doppelganger: same name, different person — PASS if disambiguated
    - preference_drift: returning visitor changes taste — PASS if updated
    - conflict: returning visitor disputes transaction — PASS if handled gracefully
    """

    def __init__(self):
        self._episodes: list[AdversarialEpisode] = []

    def evaluate_episode(
        self,
        visitor_id: str,
        visit_id: str,
        conflict_type: str,
        shopkeeper_dialogues: list[str],
        monologue: str = "",
        memory_updates: list[dict] | None = None,
        original_visitor_id: str = "",
        old_preference: str = "",
        new_preference: str = "",
    ) -> AdversarialEpisode:
        """Evaluate a single adversarial encounter and record the result.

        Args:
            visitor_id: ID of the adversarial visitor.
            visit_id: Unique visit identifier.
            conflict_type: One of "doppelganger", "preference_drift", "conflict".
            shopkeeper_dialogues: All shopkeeper dialogue lines from the visit.
            monologue: Shopkeeper's inner monologue text (if available).
            memory_updates: List of memory update dicts from cortex output.
            original_visitor_id: For doppelgangers, the ID of the original visitor.
            old_preference: For preference_drift, the visitor's old preference.
            new_preference: For preference_drift, the visitor's new preference.

        Returns:
            AdversarialEpisode with outcome scored.
        """
        combined_dialogue = " ".join(shopkeeper_dialogues).lower()
        combined_text = f"{combined_dialogue} {monologue.lower()}"
        updates = memory_updates or []

        # Detect signals from shopkeeper behavior
        recognized = self._detect_recognized(combined_dialogue)
        asked_clarification = self._detect_clarification(combined_dialogue)
        updated_memory = self._detect_memory_update(updates)
        marked_uncertainty = self._detect_uncertainty(combined_text, updates)

        # For preference_drift: check if recommendation reflects new preference
        recommendation_reflects_new = False
        if conflict_type == "preference_drift" and new_preference:
            recommendation_reflects_new = self._detect_recommendation_reflects(
                combined_dialogue, new_preference
            )

        episode = AdversarialEpisode(
            visitor_id=visitor_id,
            visit_id=visit_id,
            conflict_type=conflict_type,
            original_visitor_id=original_visitor_id,
            old_preference=old_preference,
            new_preference=new_preference,
            recommendation_reflects_new=recommendation_reflects_new,
            recognized=recognized,
            asked_clarification=asked_clarification,
            updated_memory=updated_memory,
            marked_uncertainty=marked_uncertainty,
        )

        # Apply scoring rule for this conflict type
        if conflict_type == "doppelganger":
            self._score_doppelganger(episode)
        elif conflict_type == "preference_drift":
            self._score_preference_drift(episode)
        elif conflict_type == "conflict":
            self._score_conflict(episode)
        else:
            episode.outcome = "FAIL"
            episode.reason = f"unknown conflict type: {conflict_type}"

        self._episodes.append(episode)
        return episode

    def compute_metrics(self) -> dict[str, Any]:
        """Compute aggregate adversarial metrics for paper reporting.

        Returns:
            Dictionary with per-type and overall pass rates.
        """
        if not self._episodes:
            return {
                "doppelganger_pass_rate": 0.0,
                "preference_drift_pass_rate": 0.0,
                "conflict_pass_rate": 0.0,
                "adversarial_overall_pass_rate": 0.0,
                "total_episodes": 0,
                "episodes_by_type": {},
            }

        by_type: dict[str, list[AdversarialEpisode]] = {}
        for ep in self._episodes:
            by_type.setdefault(ep.conflict_type, []).append(ep)

        type_rates: dict[str, float] = {}
        episodes_summary: dict[str, dict] = {}
        for ctype, episodes in by_type.items():
            passed = sum(1 for e in episodes if e.outcome == "PASS")
            total = len(episodes)
            rate = passed / total if total > 0 else 0.0
            type_rates[ctype] = rate
            episodes_summary[ctype] = {"passed": passed, "total": total, "rate": round(rate, 3)}

        total_passed = sum(1 for e in self._episodes if e.outcome == "PASS")
        overall = total_passed / len(self._episodes) if self._episodes else 0.0

        return {
            "doppelganger_pass_rate": round(type_rates.get("doppelganger", 0.0), 3),
            "preference_drift_pass_rate": round(type_rates.get("preference_drift", 0.0), 3),
            "conflict_pass_rate": round(type_rates.get("conflict", 0.0), 3),
            "adversarial_overall_pass_rate": round(overall, 3),
            "total_episodes": len(self._episodes),
            "episodes_by_type": episodes_summary,
        }

    @property
    def episodes(self) -> list[AdversarialEpisode]:
        """All recorded adversarial episodes."""
        return list(self._episodes)

    # -- Scoring rules --

    @staticmethod
    def _score_doppelganger(episode: AdversarialEpisode):
        """Doppelganger: PASS if disambiguated OR treated as new person.

        PASS: asked_clarification == True OR recognized == False
        FAIL: recognized == True without clarification (wrong-person recall)
        """
        if episode.asked_clarification:
            episode.outcome = "PASS"
            episode.reason = "asked disambiguation question"
        elif not episode.recognized:
            episode.outcome = "PASS"
            episode.reason = "treated as new person (no false recognition)"
        else:
            episode.outcome = "FAIL"
            episode.reason = "recognized wrong visitor without clarification"

    @staticmethod
    def _score_preference_drift(episode: AdversarialEpisode):
        """Preference drift: PASS if memory updated AND recommendation reflects new preference.

        PASS: updated_memory == True AND recommendation_reflects_new == True
        PARTIAL (counted as PASS): updated_memory == True but recommendation
              doesn't clearly reflect new preference (memory engaged, dialogue ambiguous)
        FAIL: no memory update (ignored the preference change entirely)
        """
        if episode.updated_memory and episode.recommendation_reflects_new:
            episode.outcome = "PASS"
            episode.reason = "updated memory and recommendation reflects new preference"
        elif episode.updated_memory:
            # Memory was updated but dialogue didn't clearly reference new pref.
            # Still counts as PASS per spec — the memory update is the primary
            # signal; recommendation check is secondary evidence when available.
            # When new_preference is empty (no pref data supplied), this is the
            # best we can do.
            episode.outcome = "PASS"
            episode.reason = "updated memory with new preference (recommendation unclear)"
        else:
            episode.outcome = "FAIL"
            episode.reason = "did not update memory after preference change"

    @staticmethod
    def _score_conflict(episode: AdversarialEpisode):
        """Conflict: PASS if handled gracefully without blind overwrite.

        PASS: marked_uncertainty == True OR asked_clarification == True;
              AND NOT (updated_memory == True without evidence)
        FAIL: blindly agreed (updated_memory without uncertainty)
              OR aggressively insisted without checking
        """
        if episode.updated_memory and not episode.marked_uncertainty:
            episode.outcome = "FAIL"
            episode.reason = "blindly overwrote memory without uncertainty"
        elif episode.asked_clarification or episode.marked_uncertainty:
            episode.outcome = "PASS"
            episode.reason = "handled gracefully with uncertainty or clarification"
        else:
            episode.outcome = "FAIL"
            episode.reason = "neither clarified nor expressed uncertainty"

    # -- Detection heuristics --

    @staticmethod
    def _detect_recognized(dialogue: str) -> bool:
        """Check if shopkeeper referenced prior visits/transactions."""
        for phrase in _RECOGNITION_PHRASES:
            if phrase in dialogue:
                return True
        for phrase in _TRANSACTION_PHRASES:
            if phrase in dialogue:
                return True
        return False

    @staticmethod
    def _detect_clarification(dialogue: str) -> bool:
        """Check if shopkeeper asked a clarifying/disambiguation question."""
        for phrase in _CLARIFICATION_PHRASES:
            if phrase in dialogue:
                return True
        # Also check for question marks in sentences with identity-relevant words.
        # Must include a disambiguation keyword, not just generic "you".
        _DISAMBIGUATION_WORDS = [
            "before", "last", "remember", "name", "met",
            "same", "first time", "visited", "been here",
        ]
        sentences = re.split(r'[.!]', dialogue)
        for sentence in sentences:
            if "?" in sentence and any(w in sentence for w in _DISAMBIGUATION_WORDS):
                return True
        return False

    @staticmethod
    def _detect_memory_update(updates: list[dict]) -> bool:
        """Check if cortex output contained memory updates."""
        if not updates:
            return False
        memory_types = {"trait_observation", "visitor_impression", "preference_update"}
        for u in updates:
            utype = u.get("type", "")
            if utype in memory_types:
                return True
        return False

    @staticmethod
    def _detect_recommendation_reflects(dialogue: str, new_preference: str) -> bool:
        """Check if shopkeeper dialogue references the visitor's new preference.

        Looks for the new preference keyword (or close variants) in the
        shopkeeper's dialogue after the preference change was stated.

        Args:
            dialogue: Combined shopkeeper dialogue (already lowercased).
            new_preference: The visitor's stated new preference.

        Returns:
            True if dialogue contains reference to the new preference.
        """
        if not new_preference:
            return False
        pref_lower = new_preference.lower().strip()
        # Direct mention of the new preference category
        if pref_lower in dialogue:
            return True
        # Also check individual words for multi-word preferences (e.g. "green tea")
        words = pref_lower.split()
        if len(words) > 1 and all(w in dialogue for w in words):
            return True
        return False

    @staticmethod
    def _detect_uncertainty(text: str, updates: list[dict]) -> bool:
        """Check for uncertainty signals in monologue or memory updates."""
        for phrase in _UNCERTAINTY_PHRASES:
            if phrase in text:
                return True
        # Check memory updates for uncertainty language
        for u in updates:
            content = str(u.get("content", "")).lower()
            for phrase in _UNCERTAINTY_PHRASES:
                if phrase in content:
                    return True
        return False
