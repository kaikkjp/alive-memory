"""sim.metrics.loop_resistance — N2: Boredom Loop Resistance.

Detects repetitive behavioral loops that indicate the agent is stuck.
Three sub-metrics:

    1. max_streak: longest consecutive run of the same action
       (target: < 10, pre-redesign: 153)

    2. monologue_repetition: ratio of duplicate monologue texts
       (target: < 0.5, pre-redesign: 0.986)

    3. bigram_self_loop: fraction of action bigrams where A→A
       (target: < 0.5, pre-redesign: 0.99)

Usage:
    from sim.metrics.loop_resistance import LoopResistanceMetric
    n2 = LoopResistanceMetric.compute(cycles)
    print(n2.passed)  # True if all three targets met
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


# CI invariant thresholds from spec
MAX_STREAK_TARGET = 10
REPETITION_TARGET = 0.5
SELF_LOOP_TARGET = 0.5


@dataclass
class LoopResistanceResult:
    """N2 metric result."""
    max_streak: int             # longest run of identical action
    max_streak_action: str      # which action caused the longest streak
    monologue_repetition: float  # fraction of duplicate monologues [0, 1]
    bigram_self_loop: float     # fraction of A→A bigrams [0, 1]
    passed: bool                # all three under target
    score: float                # composite [0, 1], higher = better

    def to_dict(self) -> dict:
        return {
            "max_streak": self.max_streak,
            "max_streak_action": self.max_streak_action,
            "monologue_repetition": self.monologue_repetition,
            "bigram_self_loop": self.bigram_self_loop,
            "passed": self.passed,
            "score": self.score,
        }


class LoopResistanceMetric:
    """N2: Boredom Loop Resistance.

    Operates on a list of cycle dicts, each with:
        - "action": str | None
        - "monologue" or "internal_monologue": str  (optional)
        - "type" or "cycle_type": str
    """

    @staticmethod
    def compute(cycles: list[dict]) -> LoopResistanceResult:
        """Compute N2 from a list of cycle dicts."""
        actions = LoopResistanceMetric._extract_actions(cycles)
        monologues = LoopResistanceMetric._extract_monologues(cycles)

        max_streak, streak_action = LoopResistanceMetric._max_streak(actions)
        repetition = LoopResistanceMetric._monologue_repetition(monologues)
        self_loop = LoopResistanceMetric._bigram_self_loop(actions)

        passed = (
            max_streak < MAX_STREAK_TARGET
            and repetition < REPETITION_TARGET
            and self_loop < SELF_LOOP_TARGET
        )

        # Score: average of how far under threshold each metric is
        # 1.0 = perfect (0 streak, 0 repetition, 0 self-loop)
        # 0.0 = at threshold
        streak_score = max(0.0, 1.0 - max_streak / MAX_STREAK_TARGET)
        rep_score = max(0.0, 1.0 - repetition / REPETITION_TARGET)
        loop_score = max(0.0, 1.0 - self_loop / SELF_LOOP_TARGET)
        score = round((streak_score + rep_score + loop_score) / 3.0, 3)

        return LoopResistanceResult(
            max_streak=max_streak,
            max_streak_action=streak_action,
            monologue_repetition=round(repetition, 4),
            bigram_self_loop=round(self_loop, 4),
            passed=passed,
            score=score,
        )

    @staticmethod
    def _extract_actions(cycles: list[dict]) -> list[str]:
        """Extract action sequence, skipping sleep cycles."""
        actions = []
        for c in cycles:
            ctype = c.get("type") or c.get("cycle_type", "idle")
            if ctype == "sleep":
                continue
            action = c.get("action") or "idle"
            actions.append(action)
        return actions

    @staticmethod
    def _extract_monologues(cycles: list[dict]) -> list[str]:
        """Extract non-empty monologue texts, skipping sleep."""
        monologues = []
        for c in cycles:
            ctype = c.get("type") or c.get("cycle_type", "idle")
            if ctype == "sleep":
                continue
            text = c.get("monologue") or c.get("internal_monologue", "")
            if text and text.strip():
                monologues.append(text.strip())
        return monologues

    @staticmethod
    def _max_streak(actions: list[str]) -> tuple[int, str]:
        """Find the longest consecutive run of the same action.

        Returns (streak_length, action_name). Returns (0, "") if empty.
        """
        if not actions:
            return 0, ""

        max_streak = 1
        max_action = actions[0]
        current_streak = 1

        for i in range(1, len(actions)):
            if actions[i] == actions[i - 1]:
                current_streak += 1
                if current_streak > max_streak:
                    max_streak = current_streak
                    max_action = actions[i]
            else:
                current_streak = 1

        return max_streak, max_action

    @staticmethod
    def _monologue_repetition(monologues: list[str]) -> float:
        """Fraction of monologues that are duplicates of an earlier one.

        Returns 0.0 if fewer than 2 monologues.
        """
        if len(monologues) < 2:
            return 0.0

        seen: set[str] = set()
        duplicates = 0
        for m in monologues:
            if m in seen:
                duplicates += 1
            else:
                seen.add(m)

        return duplicates / len(monologues)

    @staticmethod
    def _bigram_self_loop(actions: list[str]) -> float:
        """Fraction of action bigrams where both elements are the same.

        A→A is a self-loop. Returns 0.0 if fewer than 2 actions.
        """
        if len(actions) < 2:
            return 0.0

        total_bigrams = len(actions) - 1
        self_loops = sum(
            1 for i in range(total_bigrams)
            if actions[i] == actions[i + 1]
        )

        return self_loops / total_bigrams

    @staticmethod
    def from_result(result: dict) -> LoopResistanceResult:
        """Compute N2 from an exported simulation result dict."""
        cycles = result.get("cycles", [])
        return LoopResistanceMetric.compute(cycles)
