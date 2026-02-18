# TASK-064: Extract sleep phases to module

## Problem

`sleep.py` is accumulating phases:
- Existing consolidation
- TASK-056 meta-sleep revert
- TASK-060 self-context review
- TASK-061 organ review
- TASK-062 loop cost review
- TASK-063 fitness review

Without extraction, sleep.py becomes a 1000-line god function. Each phase has independent logic but shares the sleep runner context.

## Solution

Extract to `sleep_phases/` package with one file per phase and a thin runner in `sleep.py`. Adding future phases becomes a single file + one line in the runner.

## Package structure

```
sleep_phases/
    __init__.py          # exports phase list and runner
    consolidation.py     # existing consolidation logic
    meta_review.py       # TASK-056 revert logic
    self_context_review.py  # TASK-060 logic (added when 060 lands)
    organ_review.py      # TASK-061 logic (added when 061 lands)
```

## Runner pattern

```python
# sleep.py (after refactor)
from sleep_phases import run_all_phases

async def run_sleep(db, clock, ...):
    await run_all_phases(db, clock, ...)
```

Each phase is an async function with a standard signature:
```python
async def run(db, clock, llm_client, ...):
    """Phase description."""
    ...
```

## Scope

**Files you may touch:**
- `sleep.py` (refactor to runner that calls phases)
- `sleep_phases/__init__.py` (new)
- `sleep_phases/consolidation.py` (new — existing logic)
- `sleep_phases/meta_review.py` (new — 056 revert logic)
- `sleep_phases/self_context_review.py` (new — 060 logic)
- `sleep_phases/organ_review.py` (new — 061 logic)

**Files you may NOT touch:**
- `pipeline/*`
- `heartbeat.py`

## Tests

- All existing sleep tests pass unchanged
- Sleep output identical pre/post refactor
- Each phase can be tested in isolation

## Definition of done

- `sleep.py` is a thin runner
- Each phase is an isolated module
- Adding future phases is a single file + one line in the runner
