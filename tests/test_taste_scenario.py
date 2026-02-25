"""Tests for sim.scenarios.taste_formation — TasteFormationScenario."""

import pytest

from sim.taste.market import SimulatedMarket
from sim.taste.models import TasteEvaluation
from sim.scenarios.taste_formation import TasteFormationScenario
from sim.data.taste_listings import TASTE_LISTINGS


def _make_scenario(seed: int = 42, config: dict | None = None):
    """Helper to create a scenario with default config."""
    cfg = config or {
        "scarcity": {
            "browse_slots_per_day": 3,
            "inventory_cap": 20,
            "daily_capital": 100000,  # high enough to cover any listing price
        },
        "feedback": {"outcome_delay_cycles": 5},  # short for testing
    }
    market = SimulatedMarket(seed=seed)
    return TasteFormationScenario(
        config=cfg,
        listings=TASTE_LISTINGS,
        market=market,
        seed=seed,
    )


class TestCycleType:
    """Test 10-cycle day structure."""

    def test_browse_cycles(self):
        scenario = _make_scenario()
        assert scenario.cycle_type(0) == "browse"
        assert scenario.cycle_type(1) == "browse"
        assert scenario.cycle_type(2) == "browse"

    def test_normal_cycles(self):
        scenario = _make_scenario()
        for c in range(3, 8):
            assert scenario.cycle_type(c) == "normal"

    def test_outcome_cycle(self):
        scenario = _make_scenario()
        assert scenario.cycle_type(8) == "outcome"

    def test_sleep_cycle(self):
        scenario = _make_scenario()
        assert scenario.cycle_type(9) == "sleep"

    def test_wraps_correctly(self):
        """Day 2 should have the same pattern."""
        scenario = _make_scenario()
        assert scenario.cycle_type(10) == "browse"
        assert scenario.cycle_type(13) == "normal"
        assert scenario.cycle_type(18) == "outcome"
        assert scenario.cycle_type(19) == "sleep"

    def test_all_types_appear_in_10_cycles(self):
        """All 4 types must appear within a single day."""
        scenario = _make_scenario()
        types_seen = set()
        for c in range(10):
            types_seen.add(scenario.cycle_type(c))
        assert types_seen == {"browse", "normal", "outcome", "sleep"}


class TestProcessDecision:
    """Test decision processing with scarcity constraints."""

    def test_accept_deducts_capital(self):
        scenario = _make_scenario()
        initial_capital = scenario.capital

        evaluation = TasteEvaluation(
            item_id="L-0001", cycle=0, decision="accept",
        )
        listing = scenario.get_full_listing("L-0001")
        assert listing is not None

        result = scenario.process_decision(evaluation, cycle=0)
        assert result["accepted"] is True
        assert scenario.capital == initial_capital - listing["listed_price"]

    def test_reject_no_capital_change(self):
        scenario = _make_scenario()
        initial_capital = scenario.capital

        evaluation = TasteEvaluation(
            item_id="L-0001", cycle=0, decision="reject",
        )
        result = scenario.process_decision(evaluation, cycle=0)
        assert result["accepted"] is False
        assert scenario.capital == initial_capital

    def test_insufficient_capital(self):
        scenario = _make_scenario()
        scenario.capital = 10  # very low

        # Find a listing that costs more than 10
        expensive = None
        for l in TASTE_LISTINGS:
            if l["listed_price"] > 10:
                expensive = l
                break
        assert expensive is not None

        evaluation = TasteEvaluation(
            item_id=expensive["id"], cycle=0, decision="accept",
        )
        result = scenario.process_decision(evaluation, cycle=0)
        assert result["accepted"] is False
        assert result["reason"] == "insufficient_capital"

    def test_inventory_cap_enforced(self):
        scenario = _make_scenario()
        # Fill inventory to cap and ensure capital is high enough
        scenario.inventory = [{"item_id": f"fake_{i}"} for i in range(20)]
        scenario.capital = 1000000  # ensure capital is not the constraint

        evaluation = TasteEvaluation(
            item_id="L-0001", cycle=0, decision="accept",
        )
        result = scenario.process_decision(evaluation, cycle=0)
        assert result["accepted"] is False
        assert result["reason"] == "inventory_full"


class TestResolvePendingOutcomes:
    """Test outcome resolution after delay."""

    def test_resolve_after_delay(self):
        scenario = _make_scenario()
        # Manually add a pending outcome
        listing = TASTE_LISTINGS[0]
        scenario.pending_outcomes.append({
            "item_id": listing["id"],
            "eval_id": 1,
            "cycle_acquired": 0,
            "buy_price": listing["listed_price"],
            "listing": listing,
        })
        scenario.inventory.append({
            "item_id": listing["id"],
            "buy_price": listing["listed_price"],
            "cycle_acquired": 0,
        })

        # Before delay — nothing resolves
        resolved = scenario.resolve_pending_outcomes(3)
        assert len(resolved) == 0
        assert len(scenario.pending_outcomes) == 1

        # After delay (configured to 5 cycles)
        resolved = scenario.resolve_pending_outcomes(10)
        assert len(resolved) == 1
        assert resolved[0]["item_id"] == listing["id"]
        assert resolved[0]["cycle_outcome"] == 10
        assert "sell_price" in resolved[0]
        assert "profit" in resolved[0]
        assert "outcome_category" in resolved[0]

        # Item removed from inventory
        assert len(scenario.inventory) == 0


class TestSleep:
    """Test daily reset."""

    def test_sleep_resets_capital(self):
        scenario = _make_scenario()
        scenario.capital = 100  # depleted
        scenario.evaluations_today = 3
        scenario.day = 0

        scenario.sleep()

        assert scenario.capital == 100000  # reset to daily_capital
        assert scenario.evaluations_today == 0
        assert scenario.day == 1


class TestGetAvailableListings:
    """Test listing presentation."""

    def test_returns_5_or_6_listings(self):
        scenario = _make_scenario()
        listings = scenario.get_available_listings(0)
        assert 5 <= len(listings) <= 6

    def test_listings_are_observable_only(self):
        """Returned listings must not contain hidden fields."""
        from sim.data.taste_listings import HIDDEN_FIELDS

        scenario = _make_scenario()
        listings = scenario.get_available_listings(0)
        for listing in listings:
            for field in HIDDEN_FIELDS:
                assert field not in listing, (
                    f"Hidden field '{field}' in listing {listing.get('id')}"
                )

    def test_cursor_wraps(self):
        """Cursor should wrap and reshuffle when all listings seen."""
        scenario = _make_scenario()
        seen_ids = set()
        # Get enough batches to wrap (50 listings, 5-6 per batch → ~10 batches)
        for i in range(15):
            listings = scenario.get_available_listings(i)
            for l in listings:
                seen_ids.add(l["id"])

        # Should have seen most/all listings after 15 batches
        assert len(seen_ids) >= 40, (
            f"Only saw {len(seen_ids)} unique listings after 15 batches"
        )
