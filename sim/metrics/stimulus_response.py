"""sim.metrics.stimulus_response — N1: Stimulus-Response Coupling.

Measures whether the agent's behavior adapts when visitor arrival rate
changes.  Computes action-type percentages from two scenario results
and checks that dialogue% rises (and rearrange% falls) when visitors
increase.

Usage:
    from sim.metrics.stimulus_response import StimulusResponseMetric
    n1 = StimulusResponseMetric.from_cycles(low_cycles, high_cycles)
    print(n1.score)     # composite coupling score
    print(n1.passed)    # True if dialogue% rose and rearrange% fell
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass
class ActionProfile:
    """Action-type percentage breakdown from a set of cycles."""
    dialogue_pct: float
    browse_pct: float
    rearrange_pct: float
    idle_pct: float
    other_pct: float
    total_cycles: int

    @classmethod
    def from_cycles(cls, cycles: list[dict]) -> ActionProfile:
        """Build profile from a list of cycle dicts.

        Each dict should have at minimum:
            - "type" or "cycle_type": str
            - "action": str | None
            - "has_visitor": bool  (optional, used for context)
        """
        if not cycles:
            return cls(0.0, 0.0, 0.0, 100.0, 0.0, 0)

        counts: Counter[str] = Counter()
        for c in cycles:
            ctype = c.get("type") or c.get("cycle_type", "idle")
            action = c.get("action")

            if ctype == "sleep":
                continue  # exclude sleep from action profile

            if ctype == "dialogue" or (action and action == "speak"):
                counts["dialogue"] += 1
            elif ctype == "browse" or action in ("read_content", "browse_web"):
                counts["browse"] += 1
            elif action == "rearrange":
                counts["rearrange"] += 1
            elif ctype == "idle" or action is None:
                counts["idle"] += 1
            else:
                counts["other"] += 1

        total = sum(counts.values())
        if total == 0:
            return cls(0.0, 0.0, 0.0, 100.0, 0.0, len(cycles))

        return cls(
            dialogue_pct=round(100.0 * counts["dialogue"] / total, 2),
            browse_pct=round(100.0 * counts["browse"] / total, 2),
            rearrange_pct=round(100.0 * counts["rearrange"] / total, 2),
            idle_pct=round(100.0 * counts["idle"] / total, 2),
            other_pct=round(100.0 * counts["other"] / total, 2),
            total_cycles=len(cycles),
        )


@dataclass
class StimulusResponseResult:
    """N1 metric result comparing two scenario profiles."""
    low_profile: ActionProfile
    high_profile: ActionProfile
    dialogue_delta: float   # high - low dialogue%
    browse_delta: float     # high - low browse%
    rearrange_delta: float  # high - low rearrange%
    score: float            # composite coupling score [0, 1]
    passed: bool            # dialogue rose AND rearrange fell


class StimulusResponseMetric:
    """N1: Stimulus-Response Coupling.

    Compares action profiles between a low-visitor and high-visitor
    scenario.  A well-coupled agent shifts from idle/rearrange toward
    dialogue when visitors increase.
    """

    @staticmethod
    def compute(
        low_visitor_cycles: list[dict],
        high_visitor_cycles: list[dict],
    ) -> StimulusResponseResult:
        """Compute N1 from two sets of cycle data.

        Args:
            low_visitor_cycles: Cycles from a low-visitor scenario
                (e.g. standard, isolation).
            high_visitor_cycles: Cycles from a high-visitor scenario
                (e.g. stress, social).

        Returns:
            StimulusResponseResult with deltas and pass/fail.
        """
        low = ActionProfile.from_cycles(low_visitor_cycles)
        high = ActionProfile.from_cycles(high_visitor_cycles)

        dialogue_delta = high.dialogue_pct - low.dialogue_pct
        browse_delta = high.browse_pct - low.browse_pct
        rearrange_delta = high.rearrange_pct - low.rearrange_pct

        # Pass: dialogue% rises AND rearrange% falls (or stays at 0)
        passed = dialogue_delta > 0 and rearrange_delta <= 0

        # Score: normalized coupling strength [0, 1]
        # Higher is better — dialogue rose a lot, rearrange fell a lot
        dialogue_gain = max(0.0, dialogue_delta) / 100.0
        rearrange_drop = max(0.0, -rearrange_delta) / 100.0
        score = round(min(1.0, (dialogue_gain + rearrange_drop) / 2.0), 3)

        return StimulusResponseResult(
            low_profile=low,
            high_profile=high,
            dialogue_delta=round(dialogue_delta, 2),
            browse_delta=round(browse_delta, 2),
            rearrange_delta=round(rearrange_delta, 2),
            score=score,
            passed=passed,
        )

    @staticmethod
    def from_results(
        low_result: dict,
        high_result: dict,
    ) -> StimulusResponseResult:
        """Compute N1 from two simulation result dicts (as exported by runner).

        Extracts the 'cycles' list from each result dict.
        """
        low_cycles = low_result.get("cycles", [])
        high_cycles = high_result.get("cycles", [])
        return StimulusResponseMetric.compute(low_cycles, high_cycles)
