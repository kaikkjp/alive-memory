"""Eval case runner — replays eval cases against AliveMemory instances."""

from __future__ import annotations

import logging
import tempfile
import time
from datetime import UTC, datetime

from alive_memory.clock import SimulatedClock
from alive_memory.config import AliveConfig
from tools.evolve.scorer import aggregate_split, score_case, score_query
from tools.evolve.types import (
    CaseResult,
    EvalCase,
    EvolveScore,
    RecallScore,
    SplitResult,
)

logger = logging.getLogger(__name__)

# A case "passes" if its composite score is below this threshold.
_PASS_THRESHOLD = 0.5


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 timestamp."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def run_case(
    case: EvalCase,
    config: AliveConfig | None = None,
    embedder=None,
) -> CaseResult:
    """Run a single eval case against a fresh AliveMemory instance.

    Creates an isolated in-memory instance with a SimulatedClock, replays
    conversation turns as intake calls, advances time at configured gaps,
    runs consolidation when expected, and finally scores recall queries
    against ground truth.

    Args:
        case: The eval case to run.
        config: AliveConfig to use.  Defaults to AliveConfig() if *None*.
        embedder: Optional embedding provider for scorer cascade level 3.

    Returns:
        CaseResult with per-query scores and aggregate score.
    """
    from alive_memory import AliveMemory

    cfg = config or AliveConfig()
    result = CaseResult(
        case_id=case.id,
        category=case.category,
        difficulty=case.difficulty,
    )

    # Determine start time from the first conversation turn
    start_time = datetime.now(UTC)
    if case.conversation:
        start_time = _parse_iso(case.conversation[0].time)

    clock = SimulatedClock(start_time)

    with tempfile.TemporaryDirectory(prefix="evolve_") as tmpdir:
        mem = AliveMemory(
            storage=":memory:",
            memory_dir=tmpdir,
            config=cfg,
            clock=clock,
        )
        await mem.initialize()

        try:
            # ----------------------------------------------------------
            # Phase 1: Replay conversation turns
            # ----------------------------------------------------------
            for turn in case.conversation:
                clock.set(_parse_iso(turn.time))

                # Only intake user turns — skip assistant turns
                if turn.role == "user":
                    await mem.intake(
                        event_type="conversation",
                        content=turn.content,
                        timestamp=clock.now(),
                    )

                # Check for time gaps that fire after this turn
                # (checked for every turn, not just intaked ones,
                # since after_turn refers to conversation turn number)
                for gap in case.time_gaps:
                    if gap.after_turn == turn.turn:
                        clock.set(_parse_iso(gap.skip_to))
                        if gap.consolidation_expected:
                            try:
                                await mem.consolidate(depth="full")
                            except Exception as e:
                                result.errors.append(
                                    f"consolidate after turn {turn.turn}: {e}"
                                )

            # ----------------------------------------------------------
            # Phase 2: Execute queries and score
            # ----------------------------------------------------------
            for query in case.queries:
                clock.set(_parse_iso(query.time))

                recall_start = time.monotonic()
                context = await mem.recall(query.query)
                recall_ms = (time.monotonic() - recall_start) * 1000

                # Flatten recalled text — include semantic memory fields
                recalled_items: list[str] = (
                    context.journal_entries
                    + context.visitor_notes
                    + context.self_knowledge
                    + context.reflections
                    + context.thread_context
                    + getattr(context, "totem_facts", [])
                    + getattr(context, "trait_facts", [])
                )

                # Score this query
                qs = await score_query(recalled_items, query, embedder=embedder)
                qs.latency_ms = recall_ms
                result.per_query_scores.append(qs)

            # ----------------------------------------------------------
            # Phase 3: Aggregate per-query scores into case score
            # ----------------------------------------------------------
            if result.per_query_scores:
                n = len(result.per_query_scores)
                result.score = RecallScore(
                    precision=sum(s.precision for s in result.per_query_scores) / n,
                    completeness=sum(
                        s.completeness for s in result.per_query_scores
                    ) / n,
                    noise_rejection=sum(
                        s.noise_rejection for s in result.per_query_scores
                    ) / n,
                    ranking_quality=sum(
                        s.ranking_quality for s in result.per_query_scores
                    ) / n,
                    latency_ms=sum(
                        s.latency_ms for s in result.per_query_scores
                    ) / n,
                )
            else:
                # No queries — worst score
                result.score = RecallScore()

        except Exception as e:
            logger.error("Case %s crashed: %s", case.id, e, exc_info=True)
            result.errors.append(f"case error: {e}")
            result.score = RecallScore()  # defaults to worst (composite ~1.0)
        finally:
            await mem.close()

    return result


async def run_split(
    cases: list[EvalCase],
    config: AliveConfig | None = None,
    embedder=None,
    verbose: bool = False,
) -> SplitResult:
    """Run all cases in a split and return aggregate results.

    Args:
        cases: List of eval cases to run.
        config: AliveConfig to use.
        embedder: Optional embedding provider for scorer.
        verbose: If *True*, log progress per case.

    Returns:
        SplitResult with per-case results and pass/fail counts.
    """
    split = SplitResult(name="split")
    for case in cases:
        if verbose:
            logger.info("Running case %s [%s]", case.id, case.category)

        cr = await run_case(case, config=config, embedder=embedder)
        split.case_results.append(cr)

        case_score = score_case(cr)
        if case_score < _PASS_THRESHOLD:
            split.pass_count += 1
        else:
            split.fail_count += 1

        if verbose:
            status = "PASS" if case_score < _PASS_THRESHOLD else "FAIL"
            logger.info(
                "  %s  composite=%.3f  errors=%d",
                status,
                case_score,
                len(cr.errors),
            )

    # Store category-adjusted aggregate (uses score_case() per result)
    split.aggregate_score = aggregate_split(split.case_results)

    return split


async def run_full_eval(
    train: list[EvalCase],
    held_out: list[EvalCase],
    production: list[EvalCase],
    config: AliveConfig | None = None,
    embedder=None,
    verbose: bool = False,
) -> EvolveScore:
    """Run all three splits and return an EvolveScore.

    Args:
        train: Training split eval cases.
        held_out: Held-out split eval cases.
        production: Production split eval cases.
        config: AliveConfig to use.
        embedder: Optional embedding provider for scorer.
        verbose: If *True*, log progress.

    Returns:
        EvolveScore with train, held_out, and production SplitResults.
    """
    if verbose:
        logger.info("=== Train split (%d cases) ===", len(train))
    train_result = await run_split(
        train, config=config, embedder=embedder, verbose=verbose,
    )
    train_result.name = "train"

    if verbose:
        logger.info("=== Held-out split (%d cases) ===", len(held_out))
    held_out_result = await run_split(
        held_out, config=config, embedder=embedder, verbose=verbose,
    )
    held_out_result.name = "held_out"

    if verbose:
        logger.info("=== Production split (%d cases) ===", len(production))
    production_result = await run_split(
        production, config=config, embedder=embedder, verbose=verbose,
    )
    production_result.name = "production"

    score = EvolveScore(
        train=train_result,
        held_out=held_out_result,
        production=production_result,
    )

    if verbose:
        logger.info(
            "Full eval complete — composite=%.3f  "
            "train=%.3f  held_out=%.3f  production=%.3f  "
            "overfitting=%.3f",
            score.composite,
            train_result.aggregate_score,
            held_out_result.aggregate_score,
            production_result.aggregate_score,
            score.overfitting_signal,
        )

    return score
