"""Pruning — remove very weak memories.

Memories below the prune threshold are permanently deleted
to prevent unbounded memory accumulation.
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.storage.base import BaseStorage


async def prune_weak(
    storage: BaseStorage,
    *,
    config: AliveConfig | None = None,
) -> int:
    """Delete memories below the prune threshold.

    Returns the number of memories pruned.
    """
    cfg = config or AliveConfig()
    threshold = cfg.get("consolidation.prune_threshold", 0.05)
    count = 0

    memories = await storage.get_memories_for_consolidation(min_age_hours=0)
    for mem in memories:
        if mem.strength <= threshold:
            await storage.delete_memory(mem.id)
            count += 1

    return count
