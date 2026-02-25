"""sim.scenarios.taste_formation — Taste experiment scenario controller.

NOT a ScenarioManager subclass. This is a controller that sits alongside
the runner's main loop and intercepts cycles for browse/outcome/sleep.

Day structure (~10 cycles per day):
  Cycles 0-2: browse (evaluate listings)
  Cycles 3-7: normal ALIVE cycles
  Cycle 8:    outcome resolution
  Cycle 9:    sleep (budget reset)

Scarcity constraints:
  browse_slots_per_day: 3
  daily_capital: 500¥
  inventory_cap: 20
"""

from __future__ import annotations

import random

from sim.taste.market import SimulatedMarket


class TasteFormationScenario:
    """Controller for the taste formation experiment."""

    def __init__(
        self,
        config: dict,
        listings: list[dict],
        market: SimulatedMarket,
        seed: int = 42,
    ):
        self.config = config
        self.all_listings = list(listings)
        self.market = market
        self.rng = random.Random(seed)

        # Scarcity params
        scarcity = config.get("scarcity", {})
        self.browse_slots_per_day = scarcity.get("browse_slots_per_day", 3)
        self.inventory_cap = scarcity.get("inventory_cap", 20)
        self.daily_capital = scarcity.get("daily_capital", 500)
        self.outcome_delay = config.get("feedback", {}).get(
            "outcome_delay_cycles", 50,
        )

        # State
        self.day = 0
        self.capital = self.daily_capital
        self.evaluations_today = 0
        self.inventory: list[dict] = []  # held items
        self.pending_outcomes: list[dict] = []

        # Listings cursor — cycles through all listings with wrap
        self._listing_cursor = 0
        self._shuffled_ids = list(range(len(self.all_listings)))
        self.rng.shuffle(self._shuffled_ids)

    def cycle_type(self, cycle: int) -> str:
        """Determine cycle type within a 10-cycle day.

        Returns: 'browse' | 'normal' | 'outcome' | 'sleep'
        """
        phase = cycle % 10
        if phase <= 2:
            return "browse"
        elif phase <= 7:
            return "normal"
        elif phase == 8:
            return "outcome"
        else:
            return "sleep"

    def get_available_listings(self, cycle: int) -> list[dict]:
        """Return next batch of observable listings (hidden fields stripped).

        Returns 5-6 listings per batch, agent evaluates up to browse_slots_per_day.
        Uses cursor-based traversal with wrap.
        """
        batch_size = self.rng.randint(5, 6)
        result = []
        for _ in range(batch_size):
            idx = self._shuffled_ids[self._listing_cursor % len(self._shuffled_ids)]
            listing = self.all_listings[idx]
            # Strip hidden fields — anti-tautology gate
            observable = self.market.get_observable_listing(listing)
            result.append(observable)
            self._listing_cursor += 1
            if self._listing_cursor >= len(self._shuffled_ids):
                self._listing_cursor = 0
                self.rng.shuffle(self._shuffled_ids)
        return result

    def get_full_listing(self, item_id: str) -> dict | None:
        """Get full listing (including hidden fields) by ID. For market use."""
        for listing in self.all_listings:
            if listing["id"] == item_id:
                return listing
        return None

    def process_decision(
        self, evaluation, cycle: int,
    ) -> dict:
        """Process an evaluation decision.

        If accept: check capital + inventory constraints.
        Deduct capital, add to inventory, queue outcome.

        Returns: dict with 'accepted' bool and reason if rejected.
        """
        if evaluation.decision != "accept":
            return {"accepted": False, "reason": evaluation.decision}

        listing = self.get_full_listing(evaluation.item_id)
        if listing is None:
            return {"accepted": False, "reason": "listing_not_found"}

        buy_price = listing["listed_price"]

        # Check constraints
        if buy_price > self.capital:
            return {"accepted": False, "reason": "insufficient_capital"}

        if len(self.inventory) >= self.inventory_cap:
            return {"accepted": False, "reason": "inventory_full"}

        # Execute acquisition
        self.capital -= buy_price
        self.inventory.append({
            "item_id": evaluation.item_id,
            "buy_price": buy_price,
            "cycle_acquired": cycle,
        })
        self.pending_outcomes.append({
            "item_id": evaluation.item_id,
            "eval_id": None,  # filled by caller after DB insert
            "cycle_acquired": cycle,
            "buy_price": buy_price,
            "listing": listing,
        })

        return {"accepted": True, "buy_price": buy_price}

    def resolve_pending_outcomes(self, current_cycle: int) -> list[dict]:
        """Resolve outcomes for items past the outcome delay.

        Returns list of resolved outcome dicts.
        """
        resolved = []
        still_pending = []

        for pending in self.pending_outcomes:
            cycles_held = current_cycle - pending["cycle_acquired"]
            if cycles_held >= self.outcome_delay:
                outcome = self.market.compute_outcome(
                    pending["listing"], pending["buy_price"],
                )
                outcome["item_id"] = pending["item_id"]
                outcome["eval_id"] = pending["eval_id"]
                outcome["cycle_acquired"] = pending["cycle_acquired"]
                outcome["cycle_outcome"] = current_cycle
                resolved.append(outcome)

                # Remove from inventory
                self.inventory = [
                    item for item in self.inventory
                    if item["item_id"] != pending["item_id"]
                ]
            else:
                still_pending.append(pending)

        self.pending_outcomes = still_pending
        return resolved

    def sleep(self) -> None:
        """Reset daily capital and evaluation count. Increment day."""
        self.day += 1
        self.capital = self.daily_capital
        self.evaluations_today = 0

    def build_eval_context(self, cycle: int) -> dict:
        """Build context dict for the evaluator prompt."""
        return {
            "cycle": cycle,
            "day": self.day,
            "capital_remaining": self.capital,
            "inventory_count": len(self.inventory),
            "inventory_slots_remaining": self.inventory_cap - len(self.inventory),
            "evaluations_today": self.evaluations_today,
            "browse_slots_remaining": max(
                0, self.browse_slots_per_day - self.evaluations_today,
            ),
        }
