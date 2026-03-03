"""Self-model — persistent self-representation.

Extracted from engine/identity/self_model.py.
Stripped: file I/O (writes to JSON), hardcoded trait lists.
Kept: self-model management via storage adapter.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alive_memory.config import AliveConfig
from alive_memory.storage.base import BaseStorage
from alive_memory.types import SelfModel


async def get_self_model(storage: BaseStorage) -> SelfModel:
    """Get the current self-model from storage."""
    return await storage.get_self_model()


async def update_traits(
    storage: BaseStorage,
    trait_updates: dict[str, float],
    *,
    config: AliveConfig | None = None,
) -> SelfModel:
    """Update specific traits in the self-model.

    Args:
        storage: Storage backend.
        trait_updates: Dict of trait_name → new_value.
        config: Configuration parameters.

    Returns:
        Updated SelfModel.
    """
    model = await storage.get_self_model()

    for name, value in trait_updates.items():
        old = model.traits.get(name)
        model.traits[name] = max(-1.0, min(1.0, value))

        # Track drift
        if old is not None and abs(value - old) > 0.01:
            model.drift_history.append({
                "trait": name,
                "old": old,
                "new": value,
                "delta": value - old,
                "at": datetime.now(timezone.utc).isoformat(),
            })

    model.version += 1
    model.snapshot_at = datetime.now(timezone.utc)

    await storage.save_self_model(model)
    return model


async def update_behavioral_summary(
    storage: BaseStorage,
    summary: str,
) -> SelfModel:
    """Update the behavioral summary in the self-model."""
    model = await storage.get_self_model()
    model.behavioral_summary = summary
    model.version += 1
    model.snapshot_at = datetime.now(timezone.utc)
    await storage.save_self_model(model)
    return model


async def snapshot(storage: BaseStorage) -> SelfModel:
    """Take a snapshot of the current self-model for developmental history."""
    model = await storage.get_self_model()
    model.snapshot_at = datetime.now(timezone.utc)
    await storage.save_self_model(model)
    return model
