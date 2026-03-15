"""Developmental history — snapshots of self-model over time.

Tracks how the self-model evolves across consolidation cycles,
providing a timeline of identity development.
"""

from __future__ import annotations

from alive_memory.storage.base import BaseStorage


async def get_history(
    storage: BaseStorage,
    *,
    from_version: int = 0,
    to_version: int | None = None,
) -> list[dict]:
    """Get developmental history from drift records in the self-model.

    Returns a timeline of trait changes.
    """
    model = await storage.get_self_model()

    history = []
    for entry in model.drift_history:
        version = entry.get("version", 0)
        if version < from_version:
            continue
        if to_version is not None and version > to_version:
            continue
        history.append(entry)

    return history


async def get_trait_timeline(
    storage: BaseStorage,
    trait_name: str,
) -> list[dict]:
    """Get the change history for a specific trait.

    Returns list of {old, new, delta, at} dicts for this trait.
    """
    model = await storage.get_self_model()

    return [
        entry for entry in model.drift_history
        if entry.get("trait") == trait_name
    ]


async def summarize_development(
    storage: BaseStorage,
) -> dict:
    """Generate a summary of identity development.

    Returns dict with:
    - total_versions: how many self-model updates
    - most_changed_traits: traits with the most cumulative drift
    - recent_direction: overall direction of recent changes
    """
    model = await storage.get_self_model()

    trait_totals: dict[str, float] = {}
    for entry in model.drift_history:
        trait = entry.get("trait", "")
        delta = entry.get("delta", 0)
        trait_totals[trait] = trait_totals.get(trait, 0) + abs(delta)

    sorted_traits = sorted(trait_totals.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_versions": model.version,
        "total_drift_events": len(model.drift_history),
        "most_changed_traits": sorted_traits[:5],
        "current_traits": model.traits,
        "behavioral_summary": model.behavioral_summary,
    }
