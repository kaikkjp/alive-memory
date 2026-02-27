"""Sleep package — daily and nap consolidation phases.

Thin orchestrator. All logic lives in submodules:
    sleep.reflection      — LLM call, daily summary, context gathering helpers
    sleep.nap             — lighter mid-cycle nap consolidation
    sleep.meta_review     — self-modification revert, trait stability, auto-promote
    sleep.meta_controller — metric-driven self-tuning (TASK-090)
    sleep.wake            — drive reset, memory flush, thread lifecycle, content pool
    sleep.consolidation   — moment iteration, journal writes, daily summary

Public API (backward-compatible with old sleep.py):
    sleep_cycle()        — full night sleep
    nap_consolidate()    — mid-day nap
    + all individual helper functions re-exported for tests
"""

import os

import clock  # noqa: F401 — tests patch sleep.clock
import db  # noqa: F401 — tests patch sleep.db

from pipeline.cortex import cortex_call_reflect, SLEEP_REFLECTION_SYSTEM  # noqa: F401
from pipeline.hippocampus_write import hippocampus_consolidate  # noqa: F401
from config.identity import IDENTITY_COMPACT  # noqa: F401

# Re-export all phase functions for backward compatibility.
# Tests patch sleep.gather_hot_context, sleep.sleep_reflect, etc. directly.
# Phase modules use sys.modules['sleep'] late-binding to pick up these patches.
from sleep.reflection import (  # noqa: F401
    gather_hot_context,
    sleep_reflect,
    write_daily_summary,
    compute_emotional_arc_from_moments,
    extract_totems_from_reflections,
    format_traits_for_sleep,
)
from sleep.meta_review import (  # noqa: F401
    review_self_modifications,
    review_trait_stability,
    run_meta_review,
    _CATEGORY_DRIVE_MAP,
)
from sleep.wake import (  # noqa: F401
    run_wake_transition,
    reset_drives_for_morning,
    flush_day_memory,
    manage_thread_lifecycle,
    cleanup_content_pool,
)
from sleep.meta_controller import run_meta_controller, evaluate_experiments, request_correction  # noqa: F401
from sleep.consolidation import run_consolidation  # noqa: F401
from sleep.nap import nap_consolidate  # noqa: F401
from sleep.whisper import process_whispers, translate_whisper  # noqa: F401

COLD_SEARCH_ENABLED = os.getenv('COLD_SEARCH_ENABLED', 'false').lower() == 'true'


async def sleep_cycle(*, identity_compact: str = '',
                      has_physical: bool = True) -> int:
    """Daily consolidation. Runs 03:00-06:00 JST.

    Returns number of moments consolidated (>=0) if ran, -1 if deferred.
    Heartbeat stamps _last_sleep_date ONLY when return >= 0.
    """
    # 0. Defer if she's mid-conversation
    engagement = await db.get_engagement_state()
    if engagement.status == 'engaged':
        print("[Sleep] Deferred — currently engaged with a visitor.")
        return -1

    # 0.5. Whisper phase — integrate pending config changes as dream perceptions
    # Runs BEFORE consolidation so perceptions are available as dream context.
    dream_perceptions = await process_whispers()
    if dream_perceptions:
        print(f"[Sleep] {len(dream_perceptions)} whisper(s) woven into dreams")

    # 1-2. Consolidation (moment reflection, journal writes, daily summary)
    processed_count = await run_consolidation(
        identity_compact=identity_compact, has_physical=has_physical)
    if processed_count == -1:
        return -1

    # Quiet day (0 moments): consolidation already handled drives + flush.
    # Skip meta review and wake transition — matches original sleep.py behavior.
    if processed_count == 0:
        return 0

    # 3-4. Reviews (trait stability, meta-sleep revert, auto-promote)
    await run_meta_review()

    # 5a. Meta-controller evaluation — closed-loop feedback (TASK-091)
    try:
        await evaluate_experiments()
    except Exception as e:
        print(f"  [Sleep] Meta-controller evaluation error (non-fatal): {e}")

    # 5b. Meta-controller — metric-driven parameter homeostasis (TASK-090)
    try:
        await run_meta_controller()
    except Exception as e:
        print(f"  [Sleep] Meta-controller error (non-fatal): {e}")

    # 5c. Identity evolution — three-tier drift resolution (TASK-092)
    # Runs AFTER meta-controller so it can see whether drift was already addressed.
    try:
        await _run_identity_evolution()
    except Exception as e:
        print(f"  [Sleep] Identity evolution error (non-fatal): {e}")

    # 6-10. Wake transition (threads, content pool, drives, budget reset, embedding, flush)
    await run_wake_transition()

    return processed_count


async def _run_identity_evolution() -> None:
    """Run the identity evolution phase during sleep (TASK-092).

    Detects per-parameter drift, evaluates each through the three-tier
    hierarchy, and acts (accept/correct/defer) on at most one per sleep.
    """
    from identity.evolution import IdentityEvolution, DriftReport, EvolutionAction
    from sleep.meta_controller import _get_cycle_count

    evo = IdentityEvolution()
    if not evo.enabled:
        print("  [IdentityEvolution] Disabled in config")
        return

    cycle_count = await _get_cycle_count()
    ie_config = evo._yaml_config
    window = ie_config.get('baseline_shift_window', 1000)
    min_drift = ie_config.get('drift_magnitude_threshold', 0.05)

    # Build per-parameter drift reports from modification history
    drifted = await db.get_drifted_params(
        window_cycles=window,
        cycle_count=cycle_count,
        min_drift=min_drift,
    )

    if not drifted:
        print("  [IdentityEvolution] No parameter drift detected")
        return

    print(f"  [IdentityEvolution] {len(drifted)} drifted param(s) found")

    for d in drifted:
        if not evo.can_update():
            print("  [IdentityEvolution] Rate limit reached — stopping")
            break

        report = DriftReport(
            trait_name=d['param_name'],
            baseline_value=d['baseline_value'],
            current_value=d['current_value'],
            drift_magnitude=d['drift_magnitude'],
        )

        decision = await evo.evaluate_drift(report, cycle_count)
        print(f"  [IdentityEvolution] {report.trait_name}: "
              f"{decision.action.value} — {decision.reason}")

        if decision.action == EvolutionAction.ACCEPT:
            await evo.accept_drift(report)
        elif decision.action == EvolutionAction.CORRECT:
            await evo.correct_drift(report)
        elif decision.action == EvolutionAction.DEFER:
            await evo.defer(report, decision.reason)
