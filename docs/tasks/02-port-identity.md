# Task: Port Full Identity System from Shopkeeper

## Goal
Port the complete identity system from shopkeeper's `engine/identity/` into the alive-memory SDK at `alive_memory/identity/`, replacing current stubs.

## Current State (SDK)
- `identity/self_model.py` (80L) — thin facade: get_self_model, update_traits (clamp [-1,1]), update_behavioral_summary, snapshot
- `identity/drift.py` (92L) — simple DriftReport dataclass + detect_drift() using trait consistency scoring
- `identity/evolution.py` (112L) — EvolutionDecision dataclass + evaluate_drift() three-tier logic + apply_decision()
- All use `BaseStorage` and `AliveConfig` abstractions

## Source (Shopkeeper — reference only)
- `engine/identity/self_model.py` (412L) — full SelfModel class:
  - trait_weights: introversion, curiosity, expressiveness, warmth (EMA alpha=0.05)
  - behavioral_signature: action_frequencies, drive_responses, sleep_wake_rhythm
  - relational_stance: warmth, curiosity, guardedness, avg_response_length, question_frequency
  - self_narrative + generation tracking
  - Action→trait mapping (freezesets for pos/neg indicators)
  - JSON persistence (atomic write via tempfile)
  - `update()` per-cycle from observed data
  - `needs_narrative_regen()` drift threshold check
- `engine/identity/drift.py` (535L) — full DriftDetector:
  - BehavioralBaseline: rolling averages (action freq, dialogue length, mood, energy, sleep/wake)
  - Total Variation Distance (TVD) for action frequency drift
  - Scalar drift for continuous metrics
  - Composite weighting: action_frequency=0.4, drive_response=0.3, conversation_style=0.2, sleep_wake=0.1
  - Thresholds: notable (0.3), significant (0.6)
  - Cooldown: 5 cycles between drift events
  - DriftResult with per-metric breakdown + natural language summary
- `engine/identity/evolution.py` (325L) — full IdentityEvolution:
  - EvolutionAction enum: ACCEPT, CORRECT, DEFER
  - GuardRailConfig: protected_traits, max_updates_per_sleep, min_sustained_cycles
  - Four-step decision: protect guard rails → conscious mods → meta-controller pending → baseline shift
  - Event emission for cortex awareness
  - Integration with meta-controller's request_correction()

## What to Port

### 1. Enhance `identity/self_model.py`
Port the SelfModel concept but keep it generic:
- **TraitConfig** — apps define their own trait names and action→trait mappings
  ```python
  class TraitConfig:
      trait_names: list[str]
      positive_indicators: dict[str, set[str]]  # trait → action names
      negative_indicators: dict[str, set[str]]
      ema_alpha: float = 0.05
      bounds: tuple[float, float] = (0.0, 1.0)
  ```
- **BehavioralSignature** — generic metric tracking (not hardcoded to shopkeeper fields)
- **RelationalStance** — optional, configurable fields
- **Self-narrative** management with drift-triggered regen
- **Persistence** via BaseStorage (not direct file I/O)
- Keep `update()`, `needs_narrative_regen()`, `snapshot()` patterns

### 2. Enhance `identity/drift.py`
Port full DriftDetector with abstractions:
- **BehavioralBaseline** — rolling averages, configurable metrics
- **DriftMetric protocol** — apps define what metrics to track
  ```python
  class DriftMetric(Protocol):
      name: str
      weight: float
      async def compute(self, current: dict, baseline: dict) -> float: ...
  ```
- **Built-in metrics**: TVD for frequency distributions, scalar drift for continuous values
- **Composite scoring** with configurable weights
- **Configurable thresholds** (notable, significant) and cooldown
- **DriftResult** with per-metric breakdown + summary builder
- **DriftDetector class** (not singleton — instantiate with config)

### 3. Enhance `identity/evolution.py`
Port full evolution logic:
- **GuardRailConfig** — protected traits, max updates per sleep, min sustained cycles
- **Four-step decision sequence** (generic, not shopkeeper-specific)
- **CorrectionProvider protocol** — apps provide correction mechanism
  ```python
  class CorrectionProvider(Protocol):
      async def request_correction(self, trait: str, target: float, reason: str) -> bool: ...
  ```
- **Event hooks** — optional callback for drift events (accept/correct/defer)
- Integration with meta-controller via CorrectionProvider

### 4. Update `identity/__init__.py`
Export all new public symbols: TraitConfig, BehavioralBaseline, DriftDetector, DriftResult, DriftMetric, GuardRailConfig, IdentityEvolution, etc.

## Design Rules
- NO hardcoded trait names (introversion, curiosity, etc.) — those are shopkeeper-specific
- All persistence via BaseStorage
- Configurable via dataclasses (TraitConfig, GuardRailConfig, DriftConfig)
- All async, type-hinted
- DriftDetector is a class (not singleton) — instantiate with config
- Pure functions where possible (TVD computation, scalar drift, etc.)

## Storage Schema
May need new storage methods for:
- Self-model persistence (traits, behavioral_signature, narrative)
- Drift history (baseline snapshots, drift events)
- Evolution decisions log

## Tests
- Unit: TVD computation, scalar drift, composite scoring, threshold detection
- Unit: Evolution decision logic (protected traits, confidence, magnitude)
- Integration: Full drift detection → evolution → correction cycle
- Integration: Self-model update → drift detection → narrative regen
- Test configurable traits (not hardcoded to shopkeeper's 4 traits)

## Files to Modify
- `alive_memory/identity/self_model.py` — rewrite
- `alive_memory/identity/drift.py` — rewrite
- `alive_memory/identity/evolution.py` — rewrite
- `alive_memory/identity/__init__.py` — update exports
- `alive_memory/storage/base.py` — add identity storage methods
- `tests/test_identity_self_model.py` — NEW or enhance
- `tests/test_identity_drift.py` — NEW or enhance
- `tests/test_identity_evolution.py` — NEW or enhance
