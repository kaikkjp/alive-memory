"""sim.content_pool — Synthetic RSS feed for simulation.

Mirrors the production feed_ingester + notifications pipeline.
Surfaces curated content items as title-only notifications each cycle,
matching the production format from pipeline/notifications.py.

TASK-086: SimContentPool
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from sim.data.content_pool_data import CONTENT_POOL


class SimContentPool:
    """Synthetic content pool that mirrors production RSS feed behavior.

    Seeded RNG ensures deterministic surfacing across runs. Items are
    weighted by interest_score — higher-interest items surface more often.
    Pool resets when all items have been seen (simulates new day's feed).
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.seen_ids: set[str] = set()
        self.consumed_ids: set[str] = set()
        self.pool = list(CONTENT_POOL)
        self.rng.shuffle(self.pool)

    def get_notifications(self, cycle: int, max_items: int = 3) -> List[Dict]:
        """Surface unseen content items as title-only notifications.

        Matches production ``get_notifications()`` return format.
        Items appear with Poisson-like probability weighted by
        interest_score. Typically 0-2 items per cycle, occasionally 3.
        """
        # Determine how many items to surface this cycle (Poisson-like)
        # Average ~0.5 items/cycle, so roughly 1 every 2 cycles
        n_items = 0
        for _ in range(max_items):
            if self.rng.random() < 0.18:  # ~18% chance per slot
                n_items += 1

        if n_items == 0:
            return []

        # Pick unseen items weighted by interest_score
        unseen = [item for item in self.pool if item["id"] not in self.seen_ids]
        if not unseen:
            # All content consumed — reset pool (simulates new day's feed)
            self.seen_ids.clear()
            unseen = list(self.pool)

        # Weighted selection without replacement
        weights = [item["interest_score"] for item in unseen]
        selected: list[dict] = []
        for _ in range(min(n_items, len(unseen))):
            chosen = self.rng.choices(unseen, weights=weights, k=1)[0]
            selected.append(chosen)
            idx = unseen.index(chosen)
            unseen.pop(idx)
            weights.pop(idx)

        # Mark as surfaced (seen) so they don't repeat immediately
        for item in selected:
            self.seen_ids.add(item["id"])

        # Return in production notification format
        notifications = []
        for item in selected:
            notifications.append({
                "type": "content",
                "title": item["title"],
                "source": item["source"],
                "content_id": item["id"],
                "topic": item["topic"],
                "interest_score": item["interest_score"],
            })

        return notifications

    def consume(self, content_id: str) -> Optional[Dict]:
        """Mark a content item as consumed and return full details.

        Called when the cortex decides to ``read_content``.
        Returns the full item including summary text, or None if
        the content_id doesn't exist in the pool (typo / hallucination).
        """
        for item in self.pool:
            if item["id"] == content_id:
                self.consumed_ids.add(content_id)
                self.seen_ids.add(content_id)
                return item
        return None

    def stats(self) -> Dict:
        """Return pool statistics for the simulation report."""
        return {
            "total_items": len(self.pool),
            "seen_count": len(self.seen_ids),
            "consumed_count": len(self.consumed_ids),
            "consumed_ids": sorted(self.consumed_ids),
        }
