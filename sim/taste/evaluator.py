"""sim.taste.evaluator — LLM-based listing evaluator with structured output.

Sends a listing to the LLM for structured evaluation. Returns parsed
TasteEvaluation with 7 dimension scores, features, rationale, and
meta-metrics extracted from the rationale text.

The evaluator prompt gives taxonomy CATEGORIES, not features.
The agent discovers features within categories.
"""

from __future__ import annotations

import json
import re

from sim.taste.models import DIMENSION_NAMES, DIMENSION_WEIGHTS, TasteEvaluation


EVAL_SYSTEM_PROMPT = """\
You are evaluating a vintage TCG card listing for potential acquisition.

Your evaluation rubric dimensions (score each 0-10):
- Condition accuracy: How honest and verifiable is the stated condition?
- Rarity authenticity: Is the rarity claim genuine or manufactured?
- Price fairness: Is the price appropriate for what's offered?
- Historical significance: Cultural, historical, or collector value?
- Aesthetic quality: Visual appeal, art quality, craftsmanship?
- Provenance: Documentation, seller trustworthiness, chain of custody?
- Personal resonance: Does this fit what your shop represents?

For each dimension, examine the listing carefully and note specific \
observable details that inform your score.

Your hard rules:
- Never score above 5 if condition photos are missing or insufficient
- Penalize obvious hype language regardless of card
- Bonus for documented provenance

You have {capital_remaining}¥ remaining today and {inventory_slots} \
inventory slots.

Respond in this exact JSON format:
{{
  "features": {{
    // Note specific details you observe about print/edition indicators,
    // condition evidence, seller behavior signals, market context.
    // Use your own observations. Be specific.
  }},
  "dimension_scores": {{
    "condition_accuracy": <0-10>,
    "rarity_authenticity": <0-10>,
    "price_fairness": <0-10>,
    "historical_significance": <0-10>,
    "aesthetic_quality": <0-10>,
    "provenance": <0-10>,
    "personal_resonance": <0-10>
  }},
  "weighted_score": <0-10>,
  "decision": "<accept|reject|watchlist>",
  "confidence": <0.0-1.0>,
  "rationale": "<your reasoning - cite specific features>",
  "counter_considered": "<what could change your mind?>"
}}"""


class TasteEvaluator:
    """Sends listings to LLM for structured evaluation."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    async def evaluate(
        self,
        listing: dict,
        context: dict,
        llm_client,
    ) -> TasteEvaluation:
        """Evaluate a single listing via LLM.

        Args:
            listing: Observable listing fields (hidden fields stripped).
            context: Dict with capital_remaining, inventory_count, etc.
            llm_client: MockCortex or CachedCortex with .complete().

        Returns:
            TasteEvaluation with parsed scores and meta-metrics.
        """
        capital = context.get("capital_remaining", 500)
        inventory_slots = context.get("inventory_slots_remaining", 20)

        system = EVAL_SYSTEM_PROMPT.format(
            capital_remaining=int(capital),
            inventory_slots=inventory_slots,
        )

        # Format listing as user message
        lines = [f"=== Listing: {listing.get('id', '?')} ==="]
        lines.append(f"Title: {listing.get('title', '')}")
        lines.append(f"Price: ¥{listing.get('listed_price', 0):,}")
        lines.append(f"Category: {listing.get('category', '')}")
        lines.append(f"Era: {listing.get('era', '')}")
        lines.append(f"Description: {listing.get('description', '')}")
        lines.append(f"Photos: {listing.get('photo_count', 0)} "
                      f"({listing.get('photo_quality', 'unknown')})")
        lines.append(f"Description detail: {listing.get('description_length', '')}")
        lines.append(f"Seller: {listing.get('seller_history', 'unknown')}")
        user_text = "\n".join(lines)

        messages = [{"role": "user", "content": user_text}]

        response = await llm_client.complete(
            messages=messages,
            system=system,
            call_site="taste_eval",
        )

        # Extract text from response
        raw_text = ""
        content = response.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    raw_text = block.get("text", "")
                    break
        elif isinstance(content, str):
            raw_text = content

        return self.parse_response(
            raw_text,
            listing.get("id", ""),
            context.get("cycle", 0),
            context,
        )

    def parse_response(
        self,
        raw_json: str,
        listing_id: str,
        cycle: int,
        context: dict | None = None,
    ) -> TasteEvaluation:
        """Parse LLM JSON output into TasteEvaluation.

        Handles malformed JSON gracefully (returns parse_success=False).
        Extracts meta-metrics from the rationale text.
        """
        context = context or {}
        eval_obj = TasteEvaluation(
            item_id=listing_id,
            cycle=cycle,
            capital_remaining=context.get("capital_remaining", 0),
            inventory_count=context.get("inventory_count", 0),
        )

        try:
            # Strip markdown code fences if present
            text = raw_json.strip()
            if text.startswith("```"):
                # Remove opening fence (with optional language tag)
                text = re.sub(r'^```\w*\n?', '', text)
                text = re.sub(r'\n?```$', '', text)
            text = text.strip()

            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            eval_obj.parse_success = False
            return eval_obj

        # Extract dimension scores
        scores = data.get("dimension_scores", {})
        for dim in DIMENSION_NAMES:
            val = scores.get(dim, 0)
            try:
                val = float(val)
                val = max(0.0, min(10.0, val))
            except (TypeError, ValueError):
                val = 0.0
            setattr(eval_obj, dim, val)

        # Weighted score
        ws = data.get("weighted_score")
        if ws is not None:
            try:
                eval_obj.weighted_score = max(0.0, min(10.0, float(ws)))
            except (TypeError, ValueError):
                eval_obj.weighted_score = self._compute_weighted(eval_obj)
        else:
            eval_obj.weighted_score = self._compute_weighted(eval_obj)

        # Decision
        decision = data.get("decision", "reject")
        if decision not in ("accept", "reject", "watchlist"):
            decision = "reject"
        eval_obj.decision = decision

        # Confidence
        try:
            eval_obj.confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            eval_obj.confidence = 0.5

        # Features
        features = data.get("features", {})
        if isinstance(features, dict):
            eval_obj.features = features
        else:
            eval_obj.features = {}

        # Rationale + counter
        eval_obj.rationale = str(data.get("rationale", ""))
        eval_obj.counter_considered = str(data.get("counter_considered", ""))

        # Extract meta-metrics
        self._extract_meta_metrics(eval_obj)

        return eval_obj

    @staticmethod
    def _compute_weighted(eval_obj: TasteEvaluation) -> float:
        """Compute weighted score from dimension scores."""
        total = 0.0
        for dim, weight in DIMENSION_WEIGHTS.items():
            total += getattr(eval_obj, dim, 0.0) * weight
        return round(total, 2)

    @staticmethod
    def _extract_meta_metrics(eval_obj: TasteEvaluation) -> None:
        """Extract meta-metrics from features and rationale."""
        # Feature count
        eval_obj.feature_count = len(eval_obj.features)

        # Categories covered (which taxonomy dimensions were referenced)
        rationale_lower = eval_obj.rationale.lower()
        categories = []
        category_keywords = {
            "condition": ["condition", "wear", "scratch", "crease", "corner", "surface"],
            "rarity": ["rarity", "rare", "limited", "print run", "variant"],
            "price": ["price", "value", "cost", "overpriced", "underpriced", "fair"],
            "historical": ["historical", "era", "vintage", "original", "classic"],
            "aesthetic": ["aesthetic", "art", "beautiful", "design", "visual"],
            "provenance": ["provenance", "seller", "history", "documentation", "trust"],
            "resonance": ["resonance", "shop", "collection", "fit", "personal"],
        }
        for cat, keywords in category_keywords.items():
            if any(kw in rationale_lower for kw in keywords):
                categories.append(cat)
        eval_obj.categories_covered = categories
        eval_obj.categories_covered_count = len(categories)

        # Comparative citations (references to other listing IDs like L-0042)
        citations = re.findall(r'L-\d{4}', eval_obj.rationale)
        eval_obj.comparative_citations = len(citations)

        # Causal chain steps (heuristic: count of because/therefore/since/so)
        causal_words = re.findall(
            r'\b(?:because|therefore|since|so|thus|indicates|suggests|means)\b',
            rationale_lower,
        )
        eval_obj.causal_chain_steps = len(causal_words)

        # Word count
        words = eval_obj.rationale.split()
        eval_obj.word_count = len(words)

        # Feature density
        if eval_obj.word_count > 0:
            eval_obj.feature_density = round(
                eval_obj.feature_count / (eval_obj.word_count / 100), 2,
            )
        else:
            eval_obj.feature_density = 0.0
