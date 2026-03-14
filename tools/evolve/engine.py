"""Evolve engine — main optimization loop using a coding agent."""

from __future__ import annotations

import logging
import tempfile
import time
from datetime import UTC, datetime

from tools.evolve.agent import (
    CodingAgent,
    apply_changes,
    reload_memory_modules,
    revert_changes,
    validate_changes,
)
from tools.evolve.analyzer import generate_failure_report
from tools.evolve.runner import run_full_eval
from tools.evolve.suite.loader import EvalSuite, load_seed_suite, load_suite
from tools.evolve.types import (
    EvolveConfig,
    EvolveResult,
    EvolveScore,
    IterationRecord,
)

logger = logging.getLogger(__name__)


async def evolve(
    *,
    evolve_config: EvolveConfig | None = None,
    llm_fn=None,
) -> EvolveResult:
    """Run the evolve optimization loop.

    This is the Karpathy loop for memory algorithms:
    1. Load eval suite
    2. Run baseline eval
    3. For each iteration:
       a. Read current source of target files
       b. Generate failure report from train split
       c. Ask coding agent to propose changes
       d. Validate changes (syntax, no forbidden imports)
       e. Apply changes to source files
       f. Reload modified modules
       g. Run full eval (train + held_out + production)
       h. Check promotion criteria
       i. If promoted: keep changes, update incumbent
       j. If not promoted: revert changes
       k. Record iteration
    4. Return EvolveResult

    Args:
        evolve_config: Configuration for the evolve run.  Defaults to
                       :class:`EvolveConfig` with default values.
        llm_fn: An :class:`~alive_memory.llm.provider.LLMProvider` instance
                used by the coding agent.  Required — raises ValueError if
                *None*.

    Returns:
        EvolveResult with best score, baseline score, and iteration log.
    """
    cfg = evolve_config or EvolveConfig()

    if llm_fn is None:
        raise ValueError(
            "llm_fn is required — pass an LLMProvider instance to evolve()."
        )

    # ── Set up coding agent ──────────────────────────────────────
    agent = CodingAgent(
        llm=llm_fn,
        target_files=cfg.target_files or None,
    )

    # ── Load eval suite ──────────────────────────────────────────
    suite: EvalSuite
    if cfg.eval_suite_path:
        suite = load_suite(cfg.eval_suite_path)
    else:
        suite = load_seed_suite()

    if cfg.verbose:
        logger.info(
            "Eval suite loaded — train=%d  held_out=%d  production=%d  version=%s",
            len(suite.train),
            len(suite.held_out),
            len(suite.production),
            suite.version,
        )

    # ── Run baseline eval ────────────────────────────────────────
    if cfg.verbose:
        logger.info("Running baseline evaluation...")

    baseline_score = await run_full_eval(
        train=suite.train,
        held_out=suite.held_out,
        production=suite.production,
        verbose=cfg.verbose,
    )

    if cfg.verbose:
        logger.info("Baseline composite: %.4f", baseline_score.composite)

    incumbent = baseline_score
    iterations: list[IterationRecord] = []
    history: list[dict] = []
    total_start = time.monotonic()

    # ── Main optimization loop ───────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="evolve_backup_") as backup_root:
        for iteration in range(cfg.budget):
            iter_start = time.monotonic()
            record = IterationRecord(
                iteration=iteration,
                timestamp=datetime.now(UTC).isoformat(),
            )

            backups: dict[str, str] = {}

            try:
                # (a) Read current source of target files
                current_sources = agent.read_target_sources()
                if not current_sources:
                    logger.warning(
                        "Iter %d: no target files found — skipping", iteration
                    )
                    record.failure_analysis = "no target files found"
                    record.elapsed_seconds = time.monotonic() - iter_start
                    iterations.append(record)
                    continue

                # (b) Generate failure report from train split
                failure_report = generate_failure_report(incumbent.train)
                record.failure_analysis = failure_report

                if cfg.verbose:
                    logger.info(
                        "Iter %d/%d: requesting change from coding agent...",
                        iteration + 1,
                        cfg.budget,
                    )

                # (c) Ask coding agent to propose changes
                changes = await agent.propose_change(
                    failure_report=failure_report,
                    current_sources=current_sources,
                    history=history,
                )

                if not changes:
                    if cfg.verbose:
                        logger.info("Iter %d: agent proposed no changes", iteration)
                    record.failure_analysis += "\nAgent proposed no changes."
                    record.elapsed_seconds = time.monotonic() - iter_start
                    iterations.append(record)
                    history.append({
                        "iteration": iteration,
                        "change_description": "(no changes proposed)",
                        "promoted": False,
                        "score_delta": 0,
                    })
                    continue

                record.source_changes = {
                    path: f"({len(code)} chars)" for path, code in changes.items()
                }

                # (d) Validate changes
                validation_errors = validate_changes(
                    changes, allowed_files=agent.target_files
                )
                if validation_errors:
                    if cfg.verbose:
                        logger.info(
                            "Iter %d: validation failed — %s",
                            iteration,
                            "; ".join(validation_errors),
                        )
                    record.failure_analysis += (
                        "\nValidation failed: " + "; ".join(validation_errors)
                    )
                    record.elapsed_seconds = time.monotonic() - iter_start
                    iterations.append(record)
                    history.append({
                        "iteration": iteration,
                        "change_description": "(validation failed)",
                        "promoted": False,
                        "score_delta": 0,
                    })
                    continue

                # (e) Apply changes to source files
                backup_dir = f"{backup_root}/iter_{iteration}"
                backups = apply_changes(changes, agent.repo_root, backup_dir)

                # (f) Reload modified modules
                reload_memory_modules(list(changes.keys()))

                # (g) Run full eval
                candidate_score = await run_full_eval(
                    train=suite.train,
                    held_out=suite.held_out,
                    production=suite.production,
                    verbose=cfg.verbose,
                )
                record.score = candidate_score

                # (h) Check promotion criteria
                promoted = should_promote(candidate_score, incumbent)

                score_delta = incumbent.composite - candidate_score.composite

                if promoted:
                    # (i) Keep changes, update incumbent
                    incumbent = candidate_score
                    record.promoted = True
                    if cfg.verbose:
                        logger.info(
                            "Iter %d/%d: PROMOTED  composite=%.4f -> %.4f  "
                            "delta=%.4f  files=%s",
                            iteration + 1,
                            cfg.budget,
                            incumbent.composite + score_delta,
                            candidate_score.composite,
                            score_delta,
                            list(changes.keys()),
                        )
                else:
                    # (j) Revert changes
                    revert_changes(backups, agent.repo_root)
                    reload_memory_modules(list(changes.keys()))

                    reason = _rejection_reason(candidate_score, incumbent)
                    if cfg.verbose:
                        logger.info(
                            "Iter %d/%d: REVERTED  composite=%.4f (was %.4f)  "
                            "reason=%s",
                            iteration + 1,
                            cfg.budget,
                            candidate_score.composite,
                            incumbent.composite,
                            reason,
                        )

                # Extract change description from agent response for history
                changed_files = ", ".join(sorted(changes.keys()))
                change_desc = f"modified {changed_files}"

                history.append({
                    "iteration": iteration,
                    "change_description": change_desc,
                    "promoted": promoted,
                    "score_delta": round(score_delta, 6),
                })

            except Exception:
                logger.error(
                    "Iter %d: unhandled exception — reverting and continuing",
                    iteration,
                    exc_info=True,
                )
                # Defensively revert if we got far enough to have backups
                try:
                    if backups:
                        revert_changes(backups, agent.repo_root)
                        reload_memory_modules(list(backups.keys()))
                except Exception:
                    logger.error(
                        "Iter %d: revert after crash also failed", iteration,
                        exc_info=True,
                    )
                record.failure_analysis += "\nIteration crashed — see logs."

            record.elapsed_seconds = time.monotonic() - iter_start
            iterations.append(record)

    # ── Build result ─────────────────────────────────────────────
    total_elapsed = time.monotonic() - total_start

    # Compute source diffs (best vs baseline) for the result
    source_diffs: dict = {}
    if incumbent is not baseline_score:
        final_sources = agent.read_target_sources()
        source_diffs = {
            path: "(modified)"
            for path in final_sources
        }

    return EvolveResult(
        best_score=incumbent,
        baseline_score=baseline_score,
        iterations=iterations,
        source_diffs=source_diffs,
        total_iterations=len(iterations),
        elapsed_seconds=total_elapsed,
    )


def should_promote(candidate: EvolveScore, incumbent: EvolveScore) -> bool:
    """Check if candidate should replace incumbent.

    From the spec section 7.2, all four conditions must be met:

    1. ``candidate.composite < incumbent.composite`` — must improve overall.
    2. ``candidate.held_out.aggregate_score <= incumbent.held_out.aggregate_score + 0.01``
       — no held-out regression beyond tolerance.
    3. ``candidate.production.aggregate_score <= incumbent.production.aggregate_score + 0.01``
       — no production regression beyond tolerance.
    4. ``candidate.overfitting_signal <= 0.15`` — train must not be much
       better than held-out (overfitting guard).
    """
    # 1. Must improve composite score (lower is better)
    if candidate.composite >= incumbent.composite:
        return False

    # 2. No held-out regression beyond tolerance
    if candidate.held_out.aggregate_score > incumbent.held_out.aggregate_score + 0.01:
        return False

    # 3. No production regression beyond tolerance
    if candidate.production.aggregate_score > incumbent.production.aggregate_score + 0.01:
        return False

    # 4. Overfitting guard
    if candidate.overfitting_signal > 0.15:
        return False

    return True


def _rejection_reason(candidate: EvolveScore, incumbent: EvolveScore) -> str:
    """Return a human-readable reason why the candidate was not promoted.

    Checks the same criteria as :func:`should_promote` and returns the
    first failing condition.
    """
    if candidate.composite >= incumbent.composite:
        return (
            f"no improvement (candidate={candidate.composite:.4f} "
            f">= incumbent={incumbent.composite:.4f})"
        )
    if candidate.held_out.aggregate_score > incumbent.held_out.aggregate_score + 0.01:
        return (
            f"held-out regression ({candidate.held_out.aggregate_score:.4f} "
            f"> {incumbent.held_out.aggregate_score:.4f} + 0.01)"
        )
    if candidate.production.aggregate_score > incumbent.production.aggregate_score + 0.01:
        return (
            f"production regression ({candidate.production.aggregate_score:.4f} "
            f"> {incumbent.production.aggregate_score:.4f} + 0.01)"
        )
    if candidate.overfitting_signal > 0.15:
        return (
            f"overfitting (signal={candidate.overfitting_signal:.4f} > 0.15)"
        )
    return "unknown"
