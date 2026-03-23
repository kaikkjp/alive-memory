"""Sleep cycle orchestrator — chains all sleep phases in order.

Phase order:
  1. Whisper        (config changes → dream perceptions)
  2. Consolidation  (moments → reflect → journal → cold embed)
  3. Meta-review    (trait stability, self-mod revert)
  4. Meta-controller (metric-driven parameter homeostasis)
  5. Identity       (drift detection → evaluate → apply)
  6. Wake           (thread lifecycle, pool cleanup, drive reset)

Each phase is fault-tolerant by default: errors are caught, logged,
and collected in the report. Set SleepConfig(fault_tolerant=False)
to let exceptions propagate.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from alive_memory.config import AliveConfig
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import SleepCycleReport

logger = logging.getLogger(__name__)


@dataclass
class SleepConfig:
    """Configuration for the full sleep cycle orchestrator."""

    enable_whispers: bool = True
    enable_meta_review: bool = True
    enable_meta_controller: bool = True
    enable_identity_evolution: bool = True
    enable_wake: bool = True
    fault_tolerant: bool = True  # continue on phase failure
    consolidation_depth: str = "full"  # "full" or "nap"


async def _run_phase(
    name: str,
    coro: Any,
    report: SleepCycleReport,
    fault_tolerant: bool,
) -> Any:
    """Run a phase, catch errors if fault_tolerant, log results."""
    try:
        result = await coro
        report.phases_completed.append(name)
        return result
    except Exception as exc:
        msg = f"Phase '{name}' failed: {exc}"
        logger.error(msg, exc_info=True)
        if fault_tolerant:
            report.errors.append(msg)
            return None
        raise


async def _collect_metrics(
    provider: Any,
    report: SleepCycleReport,
    fault_tolerant: bool,
) -> dict[str, float] | None:
    """Collect metrics while honoring fault-tolerant mode."""
    try:
        return await provider.collect_metrics()  # type: ignore[no-any-return]
    except Exception as exc:
        msg = f"Phase 'meta_controller' metric collection failed: {exc}"
        logger.error(msg, exc_info=True)
        if fault_tolerant:
            report.errors.append(msg)
            return None
        raise


async def sleep_cycle(
    storage: BaseStorage,
    writer: MemoryWriter,
    reader: MemoryReader,
    llm: LLMProvider,
    embedder: EmbeddingProvider | None = None,
    config: AliveConfig | None = None,
    *,
    # Optional providers (apps supply these)
    whispers: list[dict] | None = None,
    metrics_provider: Any | None = None,  # MetricsProvider protocol
    drive_provider: Any | None = None,  # DriveProvider protocol
    wake_hooks: Any | None = None,  # WakeHooks protocol
    correction_provider: Any | None = None,  # CorrectionProvider protocol
    metric_targets: list | None = None,  # list[MetricTarget]
    protected_traits: dict[str, tuple[float, float]] | None = None,
    # Config
    sleep_config: SleepConfig | None = None,
) -> SleepCycleReport:
    """Run a complete sleep cycle.

    Chains all sleep phases in order with per-phase fault tolerance.
    Only the storage, writer, reader, and llm parameters are required.
    All other providers are optional — phases that require missing
    providers are silently skipped.

    Args:
        storage: Storage backend (Tier 1 + Tier 3).
        writer: Hot memory writer (Tier 2).
        reader: Hot memory reader (Tier 2).
        llm: LLM provider (for consolidation reflection/dreaming).
        embedder: Embedding provider (for cold archive).
        config: AliveConfig instance.
        whispers: Config changes to process as dream perceptions.
        metrics_provider: Provider with collect_metrics() method.
        drive_provider: Provider for meta-review drive access.
        wake_hooks: Provider for wake transition hooks.
        correction_provider: Provider for correction suggestions.
        metric_targets: List of MetricTarget for meta-controller.
        protected_traits: Dict of trait_name → (min_bound, max_bound).
        sleep_config: Per-cycle configuration overrides.

    Returns:
        SleepCycleReport with per-phase results and errors.
    """
    cfg = config or AliveConfig()
    sc = sleep_config or SleepConfig()
    ft = sc.fault_tolerant
    start = time.monotonic()
    report = SleepCycleReport(depth=sc.consolidation_depth)

    whisper_dreams: list[str] = []

    # ── Phase 1: Whisper ─────────────────────────────────────────
    if sc.enable_whispers and whispers:
        try:
            from alive_memory.consolidation.whisper import process_whispers
        except ImportError:
            logger.warning("Whisper module not available, skipping phase")
        else:
            result = await _run_phase(
                "whisper", process_whispers(whispers, storage), report, ft
            )
            if result:
                whisper_dreams = result

    # ── Phase 2: Consolidation ───────────────────────────────────
    from alive_memory.consolidation import consolidate

    sleep_report = await _run_phase(
        "consolidation",
        consolidate(
            storage,
            writer=writer,
            reader=reader,
            llm=llm,
            embedder=embedder,
            config=cfg,
            whispers=None,  # already processed in phase 1
            depth=sc.consolidation_depth,
        ),
        report,
        ft,
    )
    if sleep_report:
        report.moments_consolidated = sleep_report.moments_processed
        report.journal_entries_written = sleep_report.journal_entries_written
        report.dreams_generated = len(sleep_report.dreams)
    if whisper_dreams:
        report.dreams_generated += len(whisper_dreams)

    # ── Phase 3: Meta-review ─────────────────────────────────────
    if sc.enable_meta_review and drive_provider:
        try:
            from alive_cognition.meta.review import run_meta_review
        except ImportError:
            logger.warning("Meta-review module not available, skipping phase")
        else:
            await _run_phase(
                "meta_review",
                run_meta_review(storage, drive_provider=drive_provider, config=cfg),
                report,
                ft,
            )

    # ── Phase 4: Evaluation + Meta-controller ────────────────────
    if sc.enable_meta_controller and metrics_provider:
        try:
            from alive_cognition.meta.controller import run_meta_controller
        except ImportError:
            logger.warning("Meta-controller module not available, skipping phase")
        else:
            metrics = await _collect_metrics(metrics_provider, report, ft)
            if metrics is not None:
                # Run controller
                experiments = await _run_phase(
                    "meta_controller",
                    run_meta_controller(
                        storage,
                        metrics,
                        metric_targets or [],
                        config=cfg,
                    ),
                    report,
                    ft,
                )
                if experiments:
                    report.parameters_adjusted = len(experiments)

    # ── Phase 5: Identity evolution ──────────────────────────────
    if sc.enable_identity_evolution:
        try:
            from alive_cognition.identity.drift import detect_drift
            from alive_cognition.identity.evolution import GuardRailConfig, IdentityEvolution
        except ImportError:
            logger.warning("Identity modules not available, skipping phase")
        else:
            drift_reports = await _run_phase(
                "drift_detection",
                detect_drift(storage, config=cfg),
                report,
                ft,
            )
            if drift_reports:
                report.drift_detected = True
                evolution = IdentityEvolution(
                    storage,
                    guard_rails=GuardRailConfig(
                        protected_traits=protected_traits or {}
                    ),
                    correction_provider=correction_provider,
                )
                evolution.reset_sleep_counter()
                for dr in drift_reports:
                    decision = await evolution.evaluate(dr)
                    await evolution.apply(decision)
                    report.evolution_decisions.append(decision)

    # ── Phase 6: Wake ────────────────────────────────────────────
    if sc.enable_wake and wake_hooks:
        try:
            from alive_memory.consolidation.wake import run_wake_transition
        except ImportError:
            logger.warning("Wake module not available, skipping phase")
        else:
            wake_report = await _run_phase(
                "wake",
                run_wake_transition(
                    storage,
                    hooks=wake_hooks,
                    embedder=embedder,
                ),
                report,
                ft,
            )
            report.wake_completed = wake_report is not None

    # ── Finalize ─────────────────────────────────────────────────
    report.duration_seconds = time.monotonic() - start
    return report


async def nap(
    storage: BaseStorage,
    writer: MemoryWriter,
    reader: MemoryReader,
    llm: LLMProvider,
    config: AliveConfig | None = None,
) -> SleepCycleReport:
    """Lightweight mid-cycle consolidation. No meta, no identity, no wake."""
    return await sleep_cycle(
        storage=storage,
        writer=writer,
        reader=reader,
        llm=llm,
        embedder=None,
        config=config,
        sleep_config=SleepConfig(
            enable_whispers=False,
            enable_meta_review=False,
            enable_meta_controller=False,
            enable_identity_evolution=False,
            enable_wake=False,
            consolidation_depth="nap",
        ),
    )
