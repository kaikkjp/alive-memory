"""sim.visitors.state_machine — Visitor lifecycle state machine.

Drives scripted (Tier 1) visitors through their shop visit:
ENTERING -> BROWSING -> ENGAGING -> NEGOTIATING -> DECIDING -> EXITING

Transition logic uses patience, budget, goal type, and chattiness to
determine visit duration, number of turns, and exit reason. All
randomness is seeded for reproducibility.

Usage:
    from sim.visitors.state_machine import VisitorStateMachine
    sm = VisitorStateMachine(visitor, archetype, rng)
    turns = sm.generate_visit()
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sim.visitors.models import (
    ExitReason,
    VisitorArchetype,
    VisitorInstance,
    VisitorState,
)
from sim.visitors.templates import get_template_with_fallback


MAX_TURNS = 12  # Hard cap from spec


@dataclass
class VisitTurn:
    """A single visitor turn produced by the state machine."""
    turn_number: int
    state: VisitorState
    text: str
    is_exit: bool = False
    exit_reason: ExitReason | None = None


# State transition table: which states can follow which.
# Not all transitions happen — the state machine uses goal type
# and turn progression to decide the path.
_TRANSITIONS: dict[VisitorState, list[VisitorState]] = {
    VisitorState.ENTERING: [VisitorState.BROWSING, VisitorState.ENGAGING],
    VisitorState.BROWSING: [VisitorState.ENGAGING, VisitorState.DECIDING],
    VisitorState.ENGAGING: [
        VisitorState.NEGOTIATING,
        VisitorState.DECIDING,
        VisitorState.ENGAGING,  # Can stay in engaging for multi-turn chat
    ],
    VisitorState.NEGOTIATING: [
        VisitorState.DECIDING,
        VisitorState.NEGOTIATING,  # Can haggle multiple rounds
    ],
    VisitorState.DECIDING: [VisitorState.EXITING],
    VisitorState.EXITING: [],  # Terminal state
}

# Goals that involve a negotiation phase
_NEGOTIATING_GOALS = {"buy", "sell", "trade"}

# Goals that skip browsing and go straight to engaging
_DIRECT_ENGAGE_GOALS = {"appraise", "sell"}


class VisitorStateMachine:
    """Drives a visitor through their shop visit lifecycle.

    The state machine is deterministic given the same visitor traits
    and RNG seed. It pre-generates all turns for a visit, producing
    a list of VisitTurn objects that the runner converts into
    ScenarioEvents.
    """

    def __init__(
        self,
        visitor: VisitorInstance,
        archetype: VisitorArchetype,
        rng: random.Random,
    ):
        self.visitor = visitor
        self.archetype = archetype
        self.rng = rng

        self.state = VisitorState.ENTERING
        self.turn_number = 0
        self.patience_remaining = self._initial_patience()
        self.goal_satisfied = False
        self.turns: list[VisitTurn] = []

    def _initial_patience(self) -> float:
        """Calculate initial patience (number of turns before leaving).

        Maps patience trait [0-1] to a turn count [2-MAX_TURNS].
        Low patience (0.3) = ~4 turns, high patience (0.9) = ~10 turns.
        """
        base = 2 + (MAX_TURNS - 2) * self.archetype.traits.patience
        # Add small jitter
        total = base + self.rng.uniform(-1.0, 1.0)
        return max(2.0, min(float(MAX_TURNS), total))

    def generate_visit(self) -> list[VisitTurn]:
        """Generate the complete sequence of turns for this visit.

        Returns:
            List of VisitTurn objects representing the visitor's
            dialogue through the visit lifecycle.
        """
        self.turns = []
        self.state = VisitorState.ENTERING
        self.turn_number = 0

        while self.state != VisitorState.EXITING:
            # Generate a turn for the current state
            turn = self._make_turn()
            if turn:
                self.turns.append(turn)
                self.turn_number += 1

            # Check exit conditions before transitioning
            exit_reason = self._check_exit()
            if exit_reason:
                exit_turn = self._make_exit_turn(exit_reason)
                self.turns.append(exit_turn)
                break

            # Transition to next state
            self._transition()

            # Safety: hard cap
            if self.turn_number >= MAX_TURNS:
                exit_turn = self._make_exit_turn(ExitReason.MAX_TURNS)
                self.turns.append(exit_turn)
                break

        # Guarantee an EXITING turn even when _transition() set EXITING
        # directly (e.g. DECIDING→EXITING) and the loop exited on condition.
        if not self.turns or not self.turns[-1].is_exit:
            exit_turn = self._make_exit_turn(ExitReason.NATURAL)
            self.turns.append(exit_turn)

        return self.turns

    def _make_turn(self) -> VisitTurn | None:
        """Generate dialogue for the current state.

        Returns None if no templates exist for this state (e.g.
        NEGOTIATING for a browse-only visitor).
        """
        archetype_id = self.archetype.archetype_id
        goal = self.visitor.goal
        templates = get_template_with_fallback(archetype_id, goal, self.state)

        if not templates:
            return None

        text = self.rng.choice(templates)

        return VisitTurn(
            turn_number=self.turn_number,
            state=self.state,
            text=text,
        )

    def _make_exit_turn(self, reason: ExitReason) -> VisitTurn:
        """Generate the exit dialogue."""
        self.state = VisitorState.EXITING
        archetype_id = self.archetype.archetype_id
        goal = self.visitor.goal
        templates = get_template_with_fallback(
            archetype_id, goal, VisitorState.EXITING
        )

        if templates:
            text = self.rng.choice(templates)
        else:
            text = "Goodbye."

        return VisitTurn(
            turn_number=self.turn_number,
            state=VisitorState.EXITING,
            text=text,
            is_exit=True,
            exit_reason=reason,
        )

    def _check_exit(self) -> ExitReason | None:
        """Check if any exit condition is met.

        Returns the exit reason, or None to continue.
        """
        # Patience exhausted — impatient visitors (low trait) drain faster
        drain = 2.0 - self.archetype.traits.patience  # 1.1 to 1.7
        self.patience_remaining -= drain
        if self.patience_remaining <= 0:
            return ExitReason.PATIENCE_EXHAUSTED

        # Goal satisfied (probabilistic based on state progression)
        if self.state in (VisitorState.DECIDING, VisitorState.NEGOTIATING):
            if self._roll_goal_satisfaction():
                return ExitReason.GOAL_SATISFIED

        # Budget depleted (for buy/trade goals with low budget)
        if (self.visitor.goal in ("buy", "trade")
                and self.archetype.traits.budget < 0.2
                and self.state == VisitorState.NEGOTIATING):
            if self.rng.random() < 0.5:
                return ExitReason.BUDGET_DEPLETED

        return None

    def _roll_goal_satisfaction(self) -> bool:
        """Roll to see if the visitor's goal is satisfied this turn.

        Higher knowledge and budget increase satisfaction probability
        for purchase goals. Chat/learn/browse goals satisfy more easily.
        """
        goal = self.visitor.goal
        traits = self.archetype.traits

        if goal in ("browse", "chat", "learn"):
            # These goals are easily satisfied after some engagement
            return self.rng.random() < 0.6
        elif goal == "buy":
            # Higher budget = more likely to buy
            return self.rng.random() < (0.3 + traits.budget * 0.4)
        elif goal == "sell":
            return self.rng.random() < 0.5
        elif goal == "appraise":
            return self.rng.random() < 0.7
        elif goal == "trade":
            return self.rng.random() < 0.3
        else:
            return self.rng.random() < 0.5

    def _transition(self):
        """Transition to the next state based on goal and progression."""
        goal = self.visitor.goal

        if self.state == VisitorState.ENTERING:
            if goal in _DIRECT_ENGAGE_GOALS:
                self.state = VisitorState.ENGAGING
            else:
                # Most visitors browse first, but some go straight to engaging
                if self.rng.random() < 0.3:
                    self.state = VisitorState.ENGAGING
                else:
                    self.state = VisitorState.BROWSING

        elif self.state == VisitorState.BROWSING:
            # Always move to engaging after browsing
            self.state = VisitorState.ENGAGING

        elif self.state == VisitorState.ENGAGING:
            # Stay in engaging for chatty visitors or move to negotiating/deciding
            if goal in _NEGOTIATING_GOALS:
                # For purchase goals, eventually move to negotiating
                if self.turn_number >= 3 or self.rng.random() < 0.4:
                    self.state = VisitorState.NEGOTIATING
                # else stay in ENGAGING
            else:
                # Non-purchase goals: engage for a bit, then decide
                if self.turn_number >= 3 or self.rng.random() < 0.3:
                    self.state = VisitorState.DECIDING
                # else stay in ENGAGING

        elif self.state == VisitorState.NEGOTIATING:
            # Can negotiate for 1-3 rounds based on patience
            if self.rng.random() < 0.5:
                self.state = VisitorState.DECIDING
            # else stay in NEGOTIATING

        elif self.state == VisitorState.DECIDING:
            self.state = VisitorState.EXITING
