# TASK-064: Sleep Phase Extraction

## Problem

`sleep.py` is a 480-line monolith accumulating phases. TASK-059 is adding OpenRouter routing inside sleep's LLM calls. TASK-065 adds token budgeting. TASK-060+ adds self-context injection. If we don't decompose first, every future task compounds the bloat.

Current sleep.py contains:
- `sleep_cycle()` — the main 170-line orchestrator doing everything inline
- `nap_consolidate()` — lighter mid-cycle consolidation
- `gather_hot_context()` — memory context assembly
- `format_traits_for_sleep()` — trait formatting helper
- `sleep_reflect()` — LLM call for moment reflection
- `write_daily_summary()` — daily summary index
- `compute_emotional_arc_from_moments()` — emotional arc derivation
- `extract_totems_from_reflections()` — totem extraction helper
- `flush_day_memory()` — processed memory cleanup
- `review_trait_stability()` — trait stability updates
- `review_self_modifications()` — meta-sleep revert (TASK-056)
- `manage_thread_lifecycle()` — thread dormancy/archival
- `cleanup_content_pool()` — pool item expiry
- `reset_drives_for_morning()` — drive reset

## Solution

Extract discrete sleep phases into `sleep/` directory. Reduce `sleep.py` to an orchestrator that imports and calls phase functions in sequence.

## Phases to extract

### 1. Pre-sleep consolidation (`sleep/consolidation.py`)
- `sleep_cycle()` core loop: fetch unprocessed day memories, iterate moments, write journal entries
- `gather_hot_context()`, `format_traits_for_sleep()` — context assembly helpers
- Quiet-day handling (minimal journal entry when no moments)

### 2. Nap consolidation (`sleep/nap.py`)
- `nap_consolidate()` — lighter mid-cycle version
- Shares `gather_hot_context()` and `sleep_reflect()` with main consolidation

### 3. Dream/reflection generation (`sleep/reflection.py`)
- `sleep_reflect()` — the LLM call that produces reflection output
- Prompt assembly for sleep reflection
- Could also house `write_daily_summary()`, `compute_emotional_arc_from_moments()`, `extract_totems_from_reflections()`

### 4. Meta-sleep revert (`sleep/meta_review.py`)
- `review_self_modifications()` — checks drive degradation, reverts parameters
- `review_trait_stability()` — trait stability updates, anomaly archival
- `_CATEGORY_DRIVE_MAP` constant
- Auto-promote pending actions logic

### 5. Wake transition (`sleep/wake.py`)
- `reset_drives_for_morning()` — drive reset to morning defaults
- `flush_day_memory()` — processed memory cleanup + stale rows
- `manage_thread_lifecycle()` — thread dormancy/archival
- `cleanup_content_pool()` — pool item expiry
- Cold embedding (Phase 2 embedding call)
- `last_sleep_reset` timestamp write

## Target structure

```
sleep/
    __init__.py           # exports run_sleep_cycle(), run_nap()
    consolidation.py      # moment iteration, journal writes, context gathering
    nap.py                # nap_consolidate()
    reflection.py         # sleep_reflect() LLM call, daily summary, helpers
    meta_review.py        # review_self_modifications(), review_trait_stability()
    wake.py               # reset drives, flush memory, thread lifecycle, content pool
```

## Orchestrator pattern (sleep.py after refactor)

```python
# sleep.py — thin orchestrator
from sleep.consolidation import run_consolidation
from sleep.meta_review import run_meta_review
from sleep.wake import run_wake_transition

async def sleep_cycle() -> int:
    """Daily consolidation. Runs 03:00-06:00 JST."""
    # 0. Defer if engaged
    engagement = await db.get_engagement_state()
    if engagement.status == 'engaged':
        return -1

    # 1-2. Consolidation (moment reflection, journal writes)
    processed_count = await run_consolidation()
    if processed_count == -1:
        return -1

    # 3-4. Reviews (trait stability, meta-sleep revert, auto-promote)
    await run_meta_review()

    # 5-9. Wake transition (summary, threads, content pool, drives, flush)
    await run_wake_transition()

    return processed_count
```

## Rules

- Each phase becomes a function/module in `sleep/`
- `sleep.py` imports and calls them in sequence — no inline logic beyond orchestration
- **Preserve all existing behavior exactly** — this is a refactor only, no behavior changes
- Each phase must be independently testable
- **Don't touch the LLM call signatures** — TASK-059 is changing those right now. Use whatever interface exists post-059 merge
- Shared helpers (like `gather_hot_context`) should live in whichever module is their primary consumer, with imports from the other

## Scope

**Files you may touch:**
- `sleep.py` (refactor — orchestrator only after this)
- `sleep/` (new directory for extracted phases)
- `tests/` (tests for each extracted phase)

**Files you may NOT touch:**
- `pipeline/*`
- `heartbeat.py`

## Tests

- All existing sleep tests pass unchanged
- Each phase module has at least one unit test
- sleep.py line count drops by >50%

## Verification

- `scope-check.sh TASK-064` clean
- All existing sleep tests pass unchanged
- sleep.py line count drops by >50%
- Each phase module has at least one unit test

## Depends on

- TASK-059 merge (holds sleep.py — don't touch LLM call signatures)

## Blocks

- TASK-065 (prompt token budget — needs clean sleep structure)
- TASK-060 (self-context injection — adds sleep review phase)

## Definition of done

- `sleep.py` is a thin orchestrator (<100 lines)
- Each phase is an isolated, independently testable module in `sleep/`
- Adding future phases (060 self-context review, 061 organ review, 062 loop cost review, 063 fitness review) is a single file + one line in the orchestrator
- All existing behavior preserved exactly
