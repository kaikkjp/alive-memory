"""sim.taste.models — Shared dataclasses for taste evaluation experiment."""

from __future__ import annotations

from dataclasses import dataclass, field


DIMENSION_NAMES = [
    "condition_accuracy",
    "rarity_authenticity",
    "price_fairness",
    "historical_significance",
    "aesthetic_quality",
    "provenance",
    "personal_resonance",
]

DIMENSION_WEIGHTS = {
    "condition_accuracy": 0.20,
    "rarity_authenticity": 0.20,
    "price_fairness": 0.20,
    "historical_significance": 0.15,
    "aesthetic_quality": 0.15,
    "provenance": 0.05,
    "personal_resonance": 0.05,
}


@dataclass
class TasteEvaluation:
    """Result of evaluating a single listing."""

    # Identity
    item_id: str = ""
    cycle: int = 0

    # 7 dimension scores (0-10)
    condition_accuracy: float = 0.0
    rarity_authenticity: float = 0.0
    price_fairness: float = 0.0
    historical_significance: float = 0.0
    aesthetic_quality: float = 0.0
    provenance: float = 0.0
    personal_resonance: float = 0.0

    # Aggregated
    weighted_score: float = 0.0
    decision: str = "reject"  # accept | reject | watchlist
    confidence: float = 0.5

    # Structured observations
    features: dict = field(default_factory=dict)
    rationale: str = ""
    counter_considered: str = ""

    # Meta-metrics (extracted from rationale)
    feature_count: int = 0
    categories_covered: list[str] = field(default_factory=list)
    categories_covered_count: int = 0
    comparative_citations: int = 0
    causal_chain_steps: int = 0
    word_count: int = 0
    feature_density: float = 0.0

    # Capital/inventory state at decision time
    capital_remaining: float = 0.0
    inventory_count: int = 0

    # Outcome (filled later by market)
    outcome_profit: float | None = None
    outcome_sell_cycles: float | None = None
    outcome_category: str | None = None

    # Parse status
    parse_success: bool = True

    def dimension_scores(self) -> dict[str, float]:
        """Return all 7 dimension scores as a dict."""
        return {name: getattr(self, name) for name in DIMENSION_NAMES}


@dataclass
class TasteOutcome:
    """Market outcome for an acquired item."""
    item_id: str
    evaluation_id: int
    cycle_acquired: int
    cycle_outcome: int | None = None
    buy_price: float = 0.0
    sell_price: float | None = None
    profit: float | None = None
    time_to_sell: int | None = None
    outcome_category: str = "pending"  # win | loss | unsold | pending
