"""Tests for sim.taste.market — SimulatedMarket."""

import pytest
from sim.taste.market import SimulatedMarket
from sim.data.taste_listings import TASTE_LISTINGS, HIDDEN_FIELDS, OBSERVABLE_FIELDS


class TestComputeOutcome:
    """Test market outcome computation."""

    def test_returns_expected_structure(self):
        market = SimulatedMarket(seed=42)
        listing = TASTE_LISTINGS[0]  # winner
        outcome = market.compute_outcome(listing, listing["listed_price"])

        assert "sell_price" in outcome
        assert "profit" in outcome
        assert "time_to_sell" in outcome
        assert "outcome_category" in outcome

    def test_underpriced_is_usually_win(self):
        """Honest + underpriced should profit >60% of the time."""
        market = SimulatedMarket(seed=42)
        wins = 0
        trials = 0
        for listing in TASTE_LISTINGS:
            if listing.get("archetype") != "winner":
                continue
            # Buy at listed price (which is below true_value for winners)
            outcome = market.compute_outcome(listing, listing["listed_price"])
            trials += 1
            if outcome["outcome_category"] == "win":
                wins += 1

        assert trials > 0, "No winner listings found"
        win_rate = wins / trials
        assert win_rate > 0.60, f"Winners win rate {win_rate:.2f} < 0.60"

    def test_hype_listings_lose(self):
        """Hype/trap listings should lose >50% of the time."""
        market = SimulatedMarket(seed=42)
        losses = 0
        trials = 0
        for listing in TASTE_LISTINGS:
            if listing.get("archetype") != "trap":
                continue
            outcome = market.compute_outcome(listing, listing["listed_price"])
            trials += 1
            if outcome["outcome_category"] in ("loss", "unsold"):
                losses += 1

        assert trials > 0, "No trap listings found"
        loss_rate = losses / trials
        assert loss_rate > 0.50, f"Trap loss rate {loss_rate:.2f} < 0.50"

    def test_overpriced_is_unsold(self):
        """Grossly overpriced buy should result in 'unsold'."""
        market = SimulatedMarket(seed=42)
        listing = TASTE_LISTINGS[0]
        # Buy at 2x true value → price_ratio > 1.2
        outcome = market.compute_outcome(listing, listing["true_value"] * 2.5)
        assert outcome["outcome_category"] == "unsold"
        assert outcome["sell_price"] is None

    def test_zero_true_value(self):
        """Edge case: true_value = 0 → loss."""
        market = SimulatedMarket(seed=42)
        listing = {"true_value": 0, "listed_price": 100}
        outcome = market.compute_outcome(listing, 100)
        assert outcome["outcome_category"] == "loss"
        assert outcome["profit"] == -100

    def test_deterministic_with_seed(self):
        """Same seed produces same outcomes."""
        listing = TASTE_LISTINGS[0]
        m1 = SimulatedMarket(seed=99)
        m2 = SimulatedMarket(seed=99)

        o1 = m1.compute_outcome(listing, listing["listed_price"])
        o2 = m2.compute_outcome(listing, listing["listed_price"])

        assert o1 == o2


class TestObservableListing:
    """Test anti-tautology gate."""

    def test_strips_hidden_fields(self):
        """get_observable_listing must strip ALL hidden fields."""
        market = SimulatedMarket(seed=42)
        for listing in TASTE_LISTINGS:
            observable = market.get_observable_listing(listing)
            for hidden_key in HIDDEN_FIELDS:
                assert hidden_key not in observable, (
                    f"Hidden field '{hidden_key}' leaked in listing {listing['id']}"
                )

    def test_preserves_observable_fields(self):
        """Observable fields must survive stripping."""
        market = SimulatedMarket(seed=42)
        listing = TASTE_LISTINGS[0]
        observable = market.get_observable_listing(listing)

        for field in OBSERVABLE_FIELDS:
            if field in listing:
                assert field in observable, (
                    f"Observable field '{field}' was incorrectly stripped"
                )

    def test_no_true_value_in_observable(self):
        """Critical: true_value must NEVER reach the evaluator."""
        market = SimulatedMarket(seed=42)
        for listing in TASTE_LISTINGS:
            observable = market.get_observable_listing(listing)
            assert "true_value" not in observable

    def test_no_archetype_in_observable(self):
        """Archetype label must be hidden — prevents tautological learning."""
        market = SimulatedMarket(seed=42)
        for listing in TASTE_LISTINGS:
            observable = market.get_observable_listing(listing)
            assert "archetype" not in observable


class TestHiddenFactorCorrelation:
    """Test that hidden factors correlate noisily with observables."""

    def test_r_squared_hidden_vs_value_ratio(self):
        """Hidden factors should correlate with deal quality (value ratio).

        Hidden factors predict the quality of the deal (true_value / listed_price),
        not the absolute true_value. Uses manual R² computation — no scipy needed.
        """
        # Build features: seller_reliability + (1 - condition_gap) + trend_momentum
        xs = []
        ys = []
        for l in TASTE_LISTINGS:
            x = l["seller_reliability"] + (1 - abs(l["condition_gap"])) + l["trend_momentum"]
            xs.append(x)
            # Value ratio = deal quality. >1 is a good deal, <1 is a bad deal.
            ratio = l["true_value"] / l["listed_price"] if l["listed_price"] > 0 else 0
            ys.append(ratio)

        r2 = _compute_r_squared(xs, ys)
        assert 0.15 <= r2 <= 0.95, (
            f"R² of hidden factors vs value_ratio = {r2:.3f}, "
            f"expected 0.15-0.95 (noisy correlation with deal quality)"
        )

    def test_oracle_r2_below_perfect(self):
        """Even with all hidden factors, R² should be < 0.99 (noise prevents perfection)."""
        xs = []
        ys = []
        for l in TASTE_LISTINGS:
            x = (l["seller_reliability"] * 200
                 + (1 - abs(l["condition_gap"])) * 100
                 + l["trend_momentum"] * 50)
            xs.append(x)
            ratio = l["true_value"] / l["listed_price"] if l["listed_price"] > 0 else 0
            ys.append(ratio)

        r2 = _compute_r_squared(xs, ys)
        # Noise in listing creation means even an oracle can't get perfect R²
        assert r2 < 0.99, f"Oracle R² = {r2:.3f} — too close to perfect"


class TestListingsDataset:
    """Validate the listings dataset structure."""

    def test_50_listings(self):
        assert len(TASTE_LISTINGS) == 50

    def test_all_have_required_fields(self):
        required_observable = {"id", "title", "listed_price", "category"}
        required_hidden = {"true_value", "seller_reliability", "archetype"}

        for listing in TASTE_LISTINGS:
            for field in required_observable | required_hidden:
                assert field in listing, (
                    f"Listing {listing.get('id', '?')} missing field '{field}'"
                )

    def test_archetype_distribution(self):
        """Check expected archetype distribution."""
        counts = {}
        for listing in TASTE_LISTINGS:
            arch = listing["archetype"]
            counts[arch] = counts.get(arch, 0) + 1

        assert counts.get("winner", 0) >= 6
        assert counts.get("loser", 0) >= 6
        assert counts.get("mid", 0) >= 20
        assert counts.get("trap", 0) >= 3
        assert counts.get("sleeper", 0) >= 3

    def test_unique_ids(self):
        ids = [l["id"] for l in TASTE_LISTINGS]
        assert len(ids) == len(set(ids)), "Duplicate listing IDs found"


def _compute_r_squared(xs: list[float], ys: list[float]) -> float:
    """Manual R² computation without scipy."""
    n = len(xs)
    if n < 2:
        return 0.0

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_yy = sum((y - mean_y) ** 2 for y in ys)

    if ss_xx == 0 or ss_yy == 0:
        return 0.0

    r = ss_xy / (ss_xx * ss_yy) ** 0.5
    return r ** 2
