"""Decay — time-based strength reduction.

Memories that haven't been recalled gradually lose strength,
simulating the forgetting curve.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alive_memory.config import AliveConfig
from alive_memory.storage.base import BaseStorage
from alive_memory.types import Memory


async def apply_decay(
    memories: list[Memory],
    storage: BaseStorage,
    *,
    config: AliveConfig | None = None,
) -> int:
    """Apply time-based decay to memory strength.

    Returns the number of memories weakened.
    """
    cfg = config or AliveConfig()
    decay_rate = cfg.get("consolidation.decay_rate", 0.01)
    floor = cfg.get("consolidation.decay_floor", 0.05)
    count = 0

    now = datetime.now(timezone.utc)

    for mem in memories:
        formed = mem.formed_at
        if formed.tzinfo is None:
            formed = formed.replace(tzinfo=timezone.utc)
        age_hours = (now - formed).total_seconds() / 3600

        # Decay with recall-count resistance
        recall_resistance = 1.0 / (1.0 + mem.recall_count * 0.2)
        decay = decay_rate * age_hours * recall_resistance

        new_strength = max(floor, mem.strength - decay)
        if new_strength < mem.strength:
            await storage.update_memory_strength(mem.id, new_strength)
            count += 1

    return count
