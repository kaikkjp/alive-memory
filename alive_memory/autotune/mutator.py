"""Config mutation strategies for autotune."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from alive_memory.autotune.profiles import PROFILES
from alive_memory.autotune.types import ExperimentRecord
from alive_memory.config import AliveConfig


@dataclass
class TunableParam:
    """A tunable configuration parameter."""

    key: str
    param_type: str  # "float" or "int"
    min_value: float
    max_value: float
    step: float
    description: str


TUNABLE_PARAMS: list[TunableParam] = [
    TunableParam("intake.base_salience", "float", 0.1, 0.9, 0.05, "Base salience for all events"),
    TunableParam("intake.conversation_boost", "float", 0.0, 0.5, 0.05, "Extra salience for conversations"),
    TunableParam("intake.novelty_weight", "float", 0.0, 0.6, 0.05, "Weight of novelty in salience"),
    TunableParam("intake.salience_threshold", "float", 0.2, 0.7, 0.05, "Base threshold for moment formation"),
    TunableParam("intake.max_salience_threshold", "float", 0.3, 0.8, 0.05, "Max threshold at capacity"),
    TunableParam("intake.max_day_moments", "int", 10, 100, 5, "Max moments before eviction"),
    TunableParam("intake.dedup_window_minutes", "int", 5, 120, 10, "Dedup time window"),
    TunableParam("intake.dedup_similarity", "float", 0.5, 0.99, 0.05, "Fuzzy match threshold for dedup"),
    TunableParam("drives.equilibrium_pull", "float", 0.005, 0.1, 0.005, "Drive return-to-center rate"),
    TunableParam("drives.diminishing_returns", "float", 0.5, 1.0, 0.05, "Repeated stimulus multiplier"),
    TunableParam("drives.social_sensitivity", "float", 0.1, 1.0, 0.1, "Social event drive sensitivity"),
    TunableParam("consolidation.dream_count", "int", 0, 10, 1, "Dreams per consolidation"),
    TunableParam("consolidation.reflection_count", "int", 0, 5, 1, "Reflections per consolidation"),
    TunableParam("consolidation.nap_moment_count", "int", 1, 20, 2, "Moments processed in nap"),
    TunableParam("consolidation.cold_embed_limit", "int", 10, 200, 10, "Max cold embeddings per sleep"),
    TunableParam("recall.default_limit", "int", 3, 30, 2, "Max recall results per category"),
    TunableParam("recall.context_lines", "int", 1, 10, 1, "Lines of context in grep results"),
    TunableParam("identity.drift_threshold", "float", 0.05, 0.5, 0.05, "Trait change to flag as drift"),
    TunableParam("identity.ema_alpha", "float", 0.01, 0.2, 0.01, "EMA smoothing for trait updates"),
    TunableParam("identity.cooldown_cycles", "int", 1, 20, 2, "Min cycles between drift events"),
    TunableParam("identity.snapshot_interval", "int", 3, 30, 3, "Cycles between identity snapshots"),
]

# Params that are physically related — mutate together
CORRELATED_PAIRS = [
    ("intake.base_salience", "intake.salience_threshold"),
    ("intake.max_day_moments", "intake.salience_threshold"),
    ("consolidation.dream_count", "consolidation.reflection_count"),
    ("recall.default_limit", "recall.context_lines"),
    ("intake.dedup_window_minutes", "intake.dedup_similarity"),
]

_PARAM_BY_KEY = {p.key: p for p in TUNABLE_PARAMS}


class MutationStrategy(Enum):
    SINGLE_PERTURBATION = "single_perturbation"
    CORRELATED_PAIR = "correlated_pair"
    PROFILE_SWAP = "profile_swap"


def select_strategy(
    iteration: int, history: list[ExperimentRecord]
) -> MutationStrategy:
    """Select a mutation strategy based on iteration and history."""
    # Use profile swaps for the first N iterations (excluding "default")
    non_default_profiles = len(PROFILES) - 1
    if iteration < non_default_profiles:
        return MutationStrategy.PROFILE_SWAP

    # If no improvement in last 5 iterations, try correlated pair
    if len(history) >= 5 and not any(e.is_best for e in history[-5:]):
        return MutationStrategy.CORRELATED_PAIR

    return MutationStrategy.SINGLE_PERTURBATION


def mutate(
    config: AliveConfig,
    strategy: MutationStrategy,
    rng: random.Random,
    *,
    iteration: int = 0,
) -> tuple[AliveConfig, dict]:
    """Mutate a config. Returns (new_config, diff_dict)."""
    new_cfg = AliveConfig(dict(config.data))
    diff: dict = {}

    if strategy == MutationStrategy.PROFILE_SWAP:
        # Skip "default" profile (it's the baseline — already evaluated)
        profile_names = [k for k in PROFILES if k != "default"]
        idx = iteration % len(profile_names)
        profile_name = profile_names[idx]
        profile = PROFILES[profile_name]
        for key, value in profile.items():
            new_cfg.set(key, value)
            diff[key] = value
        if not diff:
            diff["_profile"] = profile_name

    elif strategy == MutationStrategy.SINGLE_PERTURBATION:
        param = rng.choice(TUNABLE_PARAMS)
        new_val = _perturb(param, config.get(param.key, 0), rng)
        new_cfg.set(param.key, new_val)
        diff[param.key] = new_val

    elif strategy == MutationStrategy.CORRELATED_PAIR:
        pair = rng.choice(CORRELATED_PAIRS)
        for key in pair:
            param = _PARAM_BY_KEY.get(key)
            if param:
                old_val = config.get(key, 0)
                new_val = _perturb(param, old_val, rng)
                new_cfg.set(key, new_val)
                diff[key] = new_val

    return new_cfg, diff


def _perturb(param: TunableParam, current: float | int, rng: random.Random) -> float | int:
    """Perturb a single parameter value within bounds."""
    scale = rng.uniform(0.5, 1.5)
    direction = rng.choice([-1, 1])
    delta = param.step * scale * direction

    new_val = current + delta
    new_val = max(param.min_value, min(param.max_value, new_val))

    if param.param_type == "int":
        return int(round(new_val))
    return round(new_val, 4)
