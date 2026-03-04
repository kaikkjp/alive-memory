# Task: Port Meta-Controller + Meta-Review from Shopkeeper

## Goal
Port the full meta-cognition system from shopkeeper's `engine/sleep/meta_controller.py` (648L) and `engine/sleep/meta_review.py` (119L) into the alive-memory SDK at `alive_memory/meta/`.

## Current State (SDK)
- `meta/controller.py` (167L) — basic metric-driven homeostasis, has: run_meta_controller, classify_outcome, compute_adaptive_cooldown
- `meta/evaluation.py` (91L) — has: evaluate_experiment, detect_side_effects
- Both use `BaseStorage` and `AliveConfig` abstractions (good)

## Source (Shopkeeper — reference only, do NOT copy blindly)
- `engine/sleep/meta_controller.py` (648L) — full implementation with:
  - `_collect_metrics()` — reads metrics_snapshots table, normalizes by config
  - `_get_cycle_count()` — total cycles from cycle_log
  - `detect_side_effects()` — flags metrics leaving target range
  - `compute_adaptive_cooldown()` — multiplier = 2.5 - 2.0 * confidence
  - `classify_outcome()` — improved/degraded/neutral
  - `evaluate_experiments()` — evaluates pending experiments, reverts degraded, updates confidence
  - `run_meta_controller()` — collects metrics → finds out-of-range → applies bounded adjustments → logs experiments
  - `request_correction()` — identity evolution correction handler
  - Hard floor bounds (Tier 1 enforcement)
  - Confidence tracking per param-metric link
  - Side-effect detection across metrics
  - Experiment logging with full lifecycle
- `engine/sleep/meta_review.py` (119L) — trait stability + self-modification revert:
  - `run_meta_review()` — orchestrator
  - `review_trait_stability()` — 3-cycle consistency → stability score
  - `review_self_modifications()` — reverts params if governed drives degraded
  - `_CATEGORY_DRIVE_MAP` — maps parameter categories to drives

## What to Port

### 1. Enhance `meta/controller.py`
Port from shopkeeper but adapt to SDK's abstraction pattern:
- **MetricsProvider protocol** — apps provide their own metric collection (SDK should NOT hardcode DB queries)
  ```python
  class MetricsProvider(Protocol):
      async def collect_metrics(self) -> dict[str, float]: ...
      async def get_cycle_count(self) -> int: ...
  ```
- **Confidence tracking** — per param-metric link confidence scores
- **Hard floor bounds** — Tier 1 enforcement (absolute bounds applied last)
- **Experiment lifecycle** — create → evaluate → revert/accept → update confidence
- **`request_correction()`** — for identity evolution to request emergency parameter resets

### 2. Enhance `meta/evaluation.py`
- Full experiment evaluation with age-gating (only evaluate after N cycles)
- Confidence update on evaluation (increase on improved, decrease on degraded)
- Revert logic with event emission

### 3. Create `meta/review.py` (NEW)
Port meta_review concept with abstraction:
- **TraitStabilityChecker protocol** — apps define what "stability" means
- **SelfModReview** — review self-modifications, revert if governed metrics degraded
- **DriveProvider protocol** — apps provide their own drive category → metric mapping
  ```python
  class DriveProvider(Protocol):
      async def get_drive_values(self) -> dict[str, float]: ...
      def get_category_drive_map(self) -> dict[str, list[str]]: ...
  ```

### 4. Update `meta/__init__.py`
Export all new public symbols.

## Design Rules
- All functions take explicit dependencies (storage, config, providers) — NO global state
- Use `BaseStorage` for all persistence
- Use Protocol classes for app-specific hooks (MetricsProvider, DriveProvider)
- All async
- Type hints on all signatures
- Keep SDK generic — shopkeeper-specific field names stay in shopkeeper

## Storage Schema Additions
If new tables/columns are needed for experiments, confidence tracking, etc., add migration methods to `BaseStorage` or create new storage protocol methods.

## Tests
- Unit tests for all pure functions (classify_outcome, compute_adaptive_cooldown, detect_side_effects)
- Integration tests with mock MetricsProvider/DriveProvider
- Test experiment lifecycle: create → evaluate → revert
- Test confidence tracking: increases on improved, decreases on degraded
- Test hard floor enforcement

## Files to Modify
- `alive_memory/meta/controller.py` — enhance
- `alive_memory/meta/evaluation.py` — enhance
- `alive_memory/meta/review.py` — NEW
- `alive_memory/meta/__init__.py` — update exports
- `alive_memory/storage/base.py` — add any needed storage methods
- `tests/test_meta_controller.py` — enhance
- `tests/test_meta_review.py` — NEW
