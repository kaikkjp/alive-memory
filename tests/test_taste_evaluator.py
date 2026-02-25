"""Tests for sim.taste.evaluator — TasteEvaluator."""

import json

import pytest
import pytest_asyncio

from sim.taste.evaluator import TasteEvaluator
from sim.taste.models import DIMENSION_NAMES, TasteEvaluation


class TestParseResponse:
    """Test parse_response with various inputs."""

    def setup_method(self):
        self.evaluator = TasteEvaluator()

    def test_valid_json(self):
        data = {
            "features": {"print_quality": "good", "centering": "off-center"},
            "dimension_scores": {
                "condition_accuracy": 7.0,
                "rarity_authenticity": 6.5,
                "price_fairness": 5.0,
                "historical_significance": 8.0,
                "aesthetic_quality": 7.5,
                "provenance": 4.0,
                "personal_resonance": 6.0,
            },
            "weighted_score": 6.3,
            "decision": "accept",
            "confidence": 0.75,
            "rationale": "Good condition and fair price because of historical value.",
            "counter_considered": "Market trends could shift.",
        }
        raw = json.dumps(data)
        result = self.evaluator.parse_response(raw, "L-0001", 5)

        assert isinstance(result, TasteEvaluation)
        assert result.item_id == "L-0001"
        assert result.cycle == 5
        assert result.condition_accuracy == 7.0
        assert result.rarity_authenticity == 6.5
        assert result.decision == "accept"
        assert result.confidence == 0.75
        assert result.parse_success is True

    def test_malformed_json(self):
        result = self.evaluator.parse_response(
            "not json at all", "L-0001", 0,
        )
        assert result.parse_success is False
        assert result.item_id == "L-0001"

    def test_markdown_fenced_json(self):
        data = {
            "features": {},
            "dimension_scores": {d: 5.0 for d in DIMENSION_NAMES},
            "weighted_score": 5.0,
            "decision": "reject",
            "confidence": 0.5,
            "rationale": "Average listing.",
            "counter_considered": "Nothing.",
        }
        raw = f"```json\n{json.dumps(data)}\n```"
        result = self.evaluator.parse_response(raw, "L-0002", 10)
        assert result.parse_success is True
        assert result.decision == "reject"

    def test_scores_clamped_0_10(self):
        data = {
            "features": {},
            "dimension_scores": {
                "condition_accuracy": 15.0,  # over 10
                "rarity_authenticity": -3.0,  # below 0
                "price_fairness": 5.0,
                "historical_significance": 5.0,
                "aesthetic_quality": 5.0,
                "provenance": 5.0,
                "personal_resonance": 5.0,
            },
            "weighted_score": 5.0,
            "decision": "reject",
            "confidence": 0.5,
            "rationale": "Test.",
            "counter_considered": "N/A.",
        }
        result = self.evaluator.parse_response(json.dumps(data), "L-0003", 0)
        assert result.condition_accuracy == 10.0  # clamped
        assert result.rarity_authenticity == 0.0   # clamped

    def test_invalid_decision_defaults_to_reject(self):
        data = {
            "features": {},
            "dimension_scores": {d: 5.0 for d in DIMENSION_NAMES},
            "weighted_score": 5.0,
            "decision": "maybe",  # invalid
            "confidence": 0.5,
            "rationale": "Unclear.",
            "counter_considered": "N/A.",
        }
        result = self.evaluator.parse_response(json.dumps(data), "L-0004", 0)
        assert result.decision == "reject"

    def test_confidence_clamped_0_1(self):
        data = {
            "features": {},
            "dimension_scores": {d: 5.0 for d in DIMENSION_NAMES},
            "weighted_score": 5.0,
            "decision": "reject",
            "confidence": 2.5,  # over 1.0
            "rationale": "Test.",
            "counter_considered": "N/A.",
        }
        result = self.evaluator.parse_response(json.dumps(data), "L-0005", 0)
        assert result.confidence == 1.0


class TestMetaMetrics:
    """Test meta-metric extraction from rationale."""

    def setup_method(self):
        self.evaluator = TasteEvaluator()

    def _make_eval(self, rationale: str, features: dict | None = None) -> TasteEvaluation:
        data = {
            "features": features or {"a": "1", "b": "2", "c": "3"},
            "dimension_scores": {d: 5.0 for d in DIMENSION_NAMES},
            "weighted_score": 5.0,
            "decision": "reject",
            "confidence": 0.5,
            "rationale": rationale,
            "counter_considered": "N/A.",
        }
        return self.evaluator.parse_response(json.dumps(data), "L-0001", 0)

    def test_feature_count(self):
        result = self._make_eval("test", {"a": "1", "b": "2"})
        assert result.feature_count == 2

    def test_word_count(self):
        result = self._make_eval("This is a five word rationale.")
        assert result.word_count == 6  # "This", "is", "a", "five", "word", "rationale."

    def test_causal_chain_steps(self):
        result = self._make_eval(
            "The price is fair because the condition is good, "
            "therefore it represents value. Since the seller is reliable, "
            "this indicates a safe purchase.",
        )
        # "because", "therefore", "Since", "indicates" = 4
        assert result.causal_chain_steps == 4

    def test_comparative_citations(self):
        result = self._make_eval(
            "Similar to L-0042 but priced lower than L-0015.",
        )
        assert result.comparative_citations == 2

    def test_categories_covered(self):
        result = self._make_eval(
            "The condition shows wear. The price is fair for this rarity level.",
        )
        assert "condition" in result.categories_covered
        assert "price" in result.categories_covered
        assert "rarity" in result.categories_covered

    def test_feature_density(self):
        result = self._make_eval(
            "One two three four five.",  # 5 words
            {"a": "1", "b": "2"},  # 2 features
        )
        # density = 2 / (5 / 100) = 40.0
        assert result.feature_density == 40.0


class TestMockEvaluate:
    """Test evaluate() with mock LLM."""

    @pytest.mark.asyncio
    async def test_mock_evaluate_returns_parsed_result(self):
        from sim.llm.mock import MockCortex

        evaluator = TasteEvaluator()
        mock_llm = MockCortex(seed=42)

        listing = {
            "id": "L-0001",
            "title": "Test Card",
            "listed_price": 200,
            "category": "test",
            "era": "1990s",
            "description": "A test listing.",
            "photo_count": 3,
            "photo_quality": "good",
            "description_length": "detailed",
            "seller_history": "established",
        }
        context = {
            "cycle": 1,
            "capital_remaining": 500,
            "inventory_count": 0,
            "inventory_slots_remaining": 20,
        }

        result = await evaluator.evaluate(listing, context, mock_llm)

        assert isinstance(result, TasteEvaluation)
        assert result.parse_success is True
        assert result.decision in ("accept", "reject", "watchlist")
        assert 0.0 <= result.weighted_score <= 10.0
        assert 0.0 <= result.confidence <= 1.0

        # All dimension scores should be valid
        for dim in DIMENSION_NAMES:
            val = getattr(result, dim)
            assert 0.0 <= val <= 10.0, f"{dim} = {val} out of range"
