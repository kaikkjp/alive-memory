"""Self-model — persistent self-representation.

Part of alive_cognition (moved from alive_memory.identity.self_model).
Enhanced with TraitConfig, EMA-based trait updates, behavioral signature,
relational stance, and self-narrative management.

Persistence via BaseStorage (no direct file I/O).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from alive_memory.config import AliveConfig
from alive_memory.storage.base import BaseStorage
from alive_memory.types import SelfModel


def _ema_update(old: float, signal: float, alpha: float) -> float:
    """Exponential moving average update (pure function)."""
    return alpha * signal + (1.0 - alpha) * old


@dataclass
class TraitConfig:
    """Application-defined trait configuration."""

    trait_names: list[str] = field(default_factory=list)
    positive_indicators: dict[str, frozenset[str]] = field(default_factory=dict)
    negative_indicators: dict[str, frozenset[str]] = field(default_factory=dict)
    ema_alpha: float = 0.05
    bounds: tuple[float, float] = (0.0, 1.0)
    initial_values: dict[str, float] = field(default_factory=dict)


class SelfModelManager:
    """Manages the persistent self-model with EMA-based trait updates."""

    def __init__(
        self,
        storage: BaseStorage,
        config: TraitConfig | None = None,
    ):
        self._storage = storage
        self._trait_config = config

    async def get(self) -> SelfModel:
        """Get the current self-model from storage."""
        return await self._storage.get_self_model()

    async def update_from_actions(self, actions: list[str]) -> SelfModel:
        """EMA update traits based on observed actions.

        For each trait, count positive/negative indicator hits in action list.
        Compute signal = (pos - neg) / total_actions, normalized to bounds.
        Apply EMA: new = alpha * signal + (1 - alpha) * old.
        Track drift for changes > 0.01.
        """
        if self._trait_config is None:
            return await self._storage.get_self_model()

        if not actions:
            return await self._storage.get_self_model()

        model = await self._storage.get_self_model()
        tc = self._trait_config
        lo, hi = tc.bounds
        total = len(actions)

        # Ensure all configured traits exist with initial values
        for name in tc.trait_names:
            if name not in model.traits:
                mid = (lo + hi) / 2.0
                model.traits[name] = tc.initial_values.get(name, mid)

        action_set = actions  # keep as list for counting

        for trait in tc.trait_names:
            pos_set = tc.positive_indicators.get(trait, frozenset())
            neg_set = tc.negative_indicators.get(trait, frozenset())

            pos_count = sum(1 for a in action_set if a in pos_set)
            neg_count = sum(1 for a in action_set if a in neg_set)

            # Signal: normalized to [-1, 1] range based on action counts
            raw_signal = (pos_count - neg_count) / total

            # Map signal from [-1,1] to bounds range
            mid = (lo + hi) / 2.0
            half_range = (hi - lo) / 2.0
            signal = mid + raw_signal * half_range

            old = model.traits[trait]
            new = _ema_update(old, signal, tc.ema_alpha)
            new = max(lo, min(hi, new))

            if abs(new - old) > 0.01:
                model.drift_history.append(
                    {
                        "trait": trait,
                        "old": old,
                        "new": new,
                        "delta": new - old,
                        "at": datetime.now(UTC).isoformat(),
                    }
                )

            model.traits[trait] = new

        model.version += 1
        model.snapshot_at = datetime.now(UTC)
        await self._storage.save_self_model(model)
        return model

    async def update_traits(self, trait_updates: dict[str, float]) -> SelfModel:
        """Direct trait update (clamped to bounds). Backward compat."""
        model = await self._storage.get_self_model()

        if self._trait_config:
            lo, hi = self._trait_config.bounds
        else:
            lo, hi = -1.0, 1.0

        for name, value in trait_updates.items():
            old = model.traits.get(name)
            clamped = max(lo, min(hi, value))
            model.traits[name] = clamped

            if old is not None and abs(clamped - old) > 0.01:
                model.drift_history.append(
                    {
                        "trait": name,
                        "old": old,
                        "new": clamped,
                        "delta": clamped - old,
                        "at": datetime.now(UTC).isoformat(),
                    }
                )

        model.version += 1
        model.snapshot_at = datetime.now(UTC)
        await self._storage.save_self_model(model)
        return model

    async def update_behavioral_signature(self, metrics: dict[str, Any]) -> SelfModel:
        """Update generic behavioral metrics (action frequencies, etc.)."""
        model = await self._storage.get_self_model()
        model.behavioral_signature.update(metrics)
        model.version += 1
        model.snapshot_at = datetime.now(UTC)
        await self._storage.save_self_model(model)
        return model

    async def update_relational_stance(self, stance: dict[str, float]) -> SelfModel:
        """Update relational metrics."""
        model = await self._storage.get_self_model()
        model.relational_stance.update(stance)
        model.version += 1
        model.snapshot_at = datetime.now(UTC)
        await self._storage.save_self_model(model)
        return model

    async def update_narrative(self, narrative: str) -> SelfModel:
        """Set self-narrative text, bump narrative_version."""
        model = await self._storage.get_self_model()
        model.self_narrative = narrative
        model.narrative_version += 1
        # Store current trait values as snapshot for future regen check
        model.behavioral_signature["narrative_trait_snapshot"] = dict(model.traits)
        model.version += 1
        model.snapshot_at = datetime.now(UTC)
        await self._storage.save_self_model(model)
        return model

    def needs_narrative_regen(self, model: SelfModel, threshold: float = 0.2) -> bool:
        """Check if traits have drifted enough since last narrative gen.

        Compare current trait values to stored 'narrative_trait_snapshot'
        in behavioral_signature. If max trait delta > threshold, return True.
        """
        snap = model.behavioral_signature.get("narrative_trait_snapshot")
        if not snap or not isinstance(snap, dict):
            # No snapshot yet — needs initial generation
            return bool(model.traits)

        if not model.traits:
            return False

        max_delta = max(
            abs(model.traits.get(t, 0.0) - snap.get(t, 0.0)) for t in set(model.traits) | set(snap)
        )
        return bool(max_delta > threshold)

    async def snapshot(self) -> SelfModel:
        """Take a snapshot of the current self-model."""
        model = await self._storage.get_self_model()
        model.snapshot_at = datetime.now(UTC)
        await self._storage.save_self_model(model)
        return model


# -- Backward-compatible free functions ----------------------------------------


async def get_self_model(storage: BaseStorage) -> SelfModel:
    """Get the current self-model from storage."""
    return await SelfModelManager(storage).get()


async def update_traits(
    storage: BaseStorage,
    trait_updates: dict[str, float],
    *,
    config: AliveConfig | None = None,
) -> SelfModel:
    """Update specific traits in the self-model.

    Backward compat: clamps to [-1, 1] when no TraitConfig is provided.
    """
    model = await storage.get_self_model()

    for name, value in trait_updates.items():
        old = model.traits.get(name)
        clamped = max(-1.0, min(1.0, value))
        model.traits[name] = clamped

        # Track drift
        if old is not None and abs(clamped - old) > 0.01:
            model.drift_history.append(
                {
                    "trait": name,
                    "old": old,
                    "new": clamped,
                    "delta": clamped - old,
                    "at": datetime.now(UTC).isoformat(),
                }
            )

    model.version += 1
    model.snapshot_at = datetime.now(UTC)

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
    model.snapshot_at = datetime.now(UTC)
    await storage.save_self_model(model)
    return model


async def snapshot(storage: BaseStorage) -> SelfModel:
    """Take a snapshot of the current self-model for developmental history."""
    return await SelfModelManager(storage).snapshot()
