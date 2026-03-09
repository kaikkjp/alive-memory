"""Autotune engine — main optimization loop."""

from __future__ import annotations

import logging
import random
import time
from datetime import UTC, datetime

from alive_memory.autotune.evaluator import aggregate_scores, score_simulation
from alive_memory.autotune.mutator import mutate, select_strategy
from alive_memory.autotune.scenarios.loader import load_scenarios
from alive_memory.autotune.simulator import run_scenario
from alive_memory.autotune.types import (
    AutotuneConfig,
    AutotuneResult,
    ExperimentRecord,
    MemoryScore,
)
from alive_memory.config import AliveConfig

logger = logging.getLogger(__name__)


async def autotune(
    config: AliveConfig | dict | None = None,
    *,
    autotune_config: AutotuneConfig | None = None,
) -> AutotuneResult:
    """Run the autotune optimization loop.

    Args:
        config: Base configuration to optimize from. Defaults to AliveConfig().
        autotune_config: Tuning parameters (budget, scenarios, etc.).

    Returns:
        AutotuneResult with best config and experiment log.
    """
    at_cfg = autotune_config or AutotuneConfig()
    rng = random.Random(at_cfg.seed)

    # Resolve base config
    if isinstance(config, dict):
        base_config = AliveConfig(config)
    elif config is None:
        base_config = AliveConfig()
    else:
        base_config = config

    # Load scenarios
    scenarios = load_scenarios(at_cfg.scenarios)
    if at_cfg.verbose:
        logger.info("Loaded %d scenarios", len(scenarios))

    # Run baseline
    baseline_scores = await _evaluate_config(base_config, scenarios)
    baseline_composite = aggregate_scores(baseline_scores)

    best_config = base_config
    best_composite = baseline_composite
    experiments: list[ExperimentRecord] = []
    total_start = time.monotonic()

    if at_cfg.verbose:
        logger.info("Baseline composite: %.4f", baseline_composite)

    for iteration in range(at_cfg.budget):
        iter_start = time.monotonic()

        # Select strategy and mutate
        strategy = select_strategy(iteration, experiments)
        candidate_config, diff = mutate(
            best_config, strategy, rng, iteration=iteration
        )

        # Evaluate candidate
        scores = await _evaluate_config(candidate_config, scenarios)
        composite = aggregate_scores(scores)

        is_best = composite < best_composite
        if is_best:
            best_config = candidate_config
            best_composite = composite

        record = ExperimentRecord(
            iteration=iteration,
            config_snapshot=dict(candidate_config.data),
            config_diff=diff,
            strategy=strategy.value,
            scores=scores,
            composite=composite,
            is_best=is_best,
            elapsed_seconds=time.monotonic() - iter_start,
            timestamp=datetime.now(UTC).isoformat(),
        )
        experiments.append(record)

        if at_cfg.verbose and (is_best or iteration % 10 == 0):
            logger.info(
                "Iter %d/%d: composite=%.4f %s (strategy=%s)",
                iteration + 1,
                at_cfg.budget,
                composite,
                "*** NEW BEST ***" if is_best else "",
                strategy.value,
            )

    total_elapsed = time.monotonic() - total_start
    improvement = (
        (baseline_composite - best_composite) / baseline_composite * 100
        if baseline_composite > 0
        else 0.0
    )

    return AutotuneResult(
        best_config=dict(best_config.data),
        baseline_composite=baseline_composite,
        best_composite=best_composite,
        improvement_pct=improvement,
        experiments=experiments,
        total_iterations=at_cfg.budget,
        elapsed_seconds=total_elapsed,
    )


async def _evaluate_config(
    config: AliveConfig,
    scenarios: list,
) -> dict[str, MemoryScore]:
    """Run all scenarios against a config and score them."""
    scores: dict[str, MemoryScore] = {}
    for scenario in scenarios:
        result = await run_scenario(scenario, config)
        scores[scenario.name] = score_simulation(result)
    return scores
