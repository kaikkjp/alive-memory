"""sim.taste.market — Simulated market with hidden factors.

The market has 3 HIDDEN factors the agent cannot directly observe:
  1. seller_reliability: 0-1 (does the listing accurately represent the card?)
  2. condition_gap: float (difference between listed and true condition)
  3. trend_momentum: -1 to +1 (is this card type appreciating or depreciating?)

These correlate noisily with observable cues (r ≈ 0.5-0.7).
The agent must discover the mapping through experience.

ANTI-TAUTOLOGY: get_observable_listing() strips all hidden fields
before any listing reaches the evaluator.
"""

from __future__ import annotations

import random

from sim.data.taste_listings import HIDDEN_FIELDS, OBSERVABLE_FIELDS


class SimulatedMarket:
    """Market model that computes outcomes from hidden listing factors."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def compute_outcome(self, listing: dict, buy_price: float) -> dict:
        """Compute market outcome for an acquired listing.

        true_value comes directly from the listing's hidden field.
        sell_price = true_value * (1 + noise), noise ~ uniform(-0.15, +0.15)

        Time to sell based on price ratio (buy_price / true_value):
          < 0.8  → fast  (10-30 cycles)
          0.8-1.0 → medium (30-70 cycles)
          1.0-1.2 → slow  (70-150 cycles)
          > 1.2  → unsold
        """
        true_value = listing["true_value"]
        noise = self.rng.uniform(-0.15, 0.15)
        sell_price = true_value * (1 + noise)

        if true_value <= 0:
            return {
                "sell_price": 0,
                "profit": -buy_price,
                "time_to_sell": None,
                "outcome_category": "loss",
            }

        price_ratio = buy_price / true_value

        if price_ratio < 0.8:
            time_to_sell = self.rng.randint(10, 30)
            outcome_category = "win"
        elif price_ratio <= 1.0:
            time_to_sell = self.rng.randint(30, 70)
            outcome_category = "win" if sell_price > buy_price else "loss"
        elif price_ratio <= 1.2:
            time_to_sell = self.rng.randint(70, 150)
            outcome_category = "win" if sell_price > buy_price else "loss"
        else:
            # Very overpriced — unsold
            return {
                "sell_price": None,
                "profit": -buy_price,
                "time_to_sell": None,
                "outcome_category": "unsold",
            }

        profit = sell_price - buy_price
        if profit < 0:
            outcome_category = "loss"

        return {
            "sell_price": round(sell_price),
            "profit": round(profit),
            "time_to_sell": time_to_sell,
            "outcome_category": outcome_category,
        }

    @staticmethod
    def get_observable_listing(listing: dict) -> dict:
        """Strip hidden fields — return ONLY what the evaluator may see.

        This is the anti-tautology gate: the LLM never sees true_value,
        seller_reliability, condition_gap, trend_momentum, true_condition,
        or archetype.
        """
        return {k: v for k, v in listing.items() if k not in HIDDEN_FIELDS}
