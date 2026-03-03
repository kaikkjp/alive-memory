"""Strengthening — rehearse and boost recently recalled memories.

Memories that have been recalled recently get a strength boost,
simulating the rehearsal effect in human memory consolidation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alive_memory.config import AliveConfig
from alive_memory.storage.base import BaseStorage
from alive_memory.types import Memory


async def strengthen(
    memories: list[Memory],
    storage: BaseStorage,
    *,
    config: AliveConfig | None = None,
) -> int:
    """Boost strength of recently recalled memories.

    Returns the number of memories strengthened.
    """
    cfg = config or AliveConfig()
    boost = cfg.get("consolidation.strengthen_boost", 0.1)
    count = 0

    for mem in memories:
        if mem.recall_count > 0 and mem.last_recalled:
            hours_since_recall = _hours_since(mem.last_recalled)
            if hours_since_recall < 24:
                recency_factor = max(0.1, 1.0 - hours_since_recall / 24.0)
                delta = boost * recency_factor

                # Recall count amplifies
                recall_factor = min(2.0, 1.0 + mem.recall_count * 0.1)
                delta *= recall_factor

                new_strength = min(1.0, mem.strength + delta)
                if new_strength > mem.strength:
                    await storage.update_memory_strength(mem.id, new_strength)
                    count += 1

    return count


def _hours_since(dt: datetime) -> float:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600
