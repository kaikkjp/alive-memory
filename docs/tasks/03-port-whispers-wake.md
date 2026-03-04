# Task: Port Enhanced Whispers + Wake Phase from Shopkeeper

## Goal
1. Enhance whisper translations in `alive_memory/consolidation/whisper.py` (6 → 10+ templates)
2. Create wake phase module at `alive_memory/consolidation/wake.py` (NEW)

## Current State (SDK)
- `consolidation/whisper.py` (63L) — 6 simple translations: curiosity, social, expression, valence, arousal, energy
- No wake phase at all — `consolidate()` does partial flush/embed inline

## Source (Shopkeeper — reference only)

### Whisper: `engine/sleep/whisper.py` (240L)
- 10 translation templates with direction-aware evocative language:
  - hypothalamus.equilibria.curiosity
  - hypothalamus.equilibria.social_hunger
  - hypothalamus.equilibria.expression_need
  - hypothalamus.equilibria.mood_valence
  - hypothalamus.equilibria.mood_arousal
  - communication_style.formality
  - communication_style.verbosity
  - sleep.morning.energy
  - sleep.morning.social_readiness
  - sleep.morning.curiosity
- `_direction()` — compares old/new numerically
- `_humanize_param_path()` — dotted path → natural language (with override map)
- Each template function returns evocative dream-like prose (increase vs decrease variants)
- `apply_config_change()` — persists via db.set_param with 'manager_whisper' source
- `process_whispers()` — translates → applies → marks processed

### Wake: `engine/sleep/wake.py` (136L)
- `run_wake_transition()` — orchestrator:
  1. `manage_thread_lifecycle()` — dormant (>48hr) → archived (>7 days)
  2. `cleanup_content_pool()` — expires items + caps unseen pool
  3. `reset_drives_for_morning()` — RMW reset to morning defaults (keeps mood)
  4. Embed cold entries (calls embed_cold.embed_cold_entries)
  5. `flush_day_memory()` — deletes processed + stale day memory rows
  6. `_update_self_memory_files()` — writes self/ MD files from self-discoveries

## What to Port

### 1. Enhance `consolidation/whisper.py`
- Add 4 missing translations: formality, verbosity, morning_energy, morning_social, morning_curiosity
- Port `_humanize_param_path()` with configurable override map
- Make translation table extensible — apps can register custom translations:
  ```python
  # Built-in translations (10)
  WHISPER_TEMPLATES: dict[str, Callable] = { ... }

  def register_whisper(param_path: str, template_fn: Callable) -> None: ...
  ```
- Keep direction-aware evocative language style
- Port the richer template prose from shopkeeper (increase/decrease variants)

### 2. Create `consolidation/wake.py` (NEW)
Port wake concepts with abstractions:
- **WakeConfig** dataclass:
  ```python
  @dataclass
  class WakeConfig:
      thread_dormant_hours: int = 48
      thread_archive_days: int = 7
      pool_max_unseen: int = 50
      stale_moment_hours: int = 72
      morning_defaults: dict[str, float] = field(default_factory=dict)
      preserve_fields: list[str] = field(default_factory=lambda: ["mood_valence"])
  ```
- **WakeHooks protocol** — apps provide lifecycle callbacks:
  ```python
  class WakeHooks(Protocol):
      async def manage_threads(self, dormant_hours: int, archive_days: int) -> int: ...
      async def cleanup_pool(self, max_unseen: int) -> int: ...
      async def reset_drives(self, defaults: dict, preserve: list[str]) -> None: ...
      async def update_self_files(self) -> None: ...
  ```
- **`run_wake_transition()`** — orchestrator calling hooks + storage flush/embed
- SDK handles: cold embedding, day memory flush (these are memory concerns)
- Apps handle: thread lifecycle, content pool, drive reset (these are app-specific)

### 3. Wire into `consolidation/__init__.py`
- Add optional wake phase after consolidation in full-depth mode
- `consolidate()` should accept optional `wake_hooks: WakeHooks` parameter
- If provided, run wake transition after consolidation

## Design Rules
- Whisper translations should be self-contained pure functions
- Wake phase uses Protocol for app-specific hooks
- SDK owns: embedding, day memory flush (memory concerns)
- App owns: threads, content pool, drives (domain concerns)
- All async, type-hinted
- No hardcoded parameter paths — configurable

## Tests
- Unit: All 10+ whisper translations (increase/decrease variants)
- Unit: _humanize_param_path with custom overrides
- Unit: Custom whisper registration
- Integration: Wake transition with mock hooks
- Integration: Full consolidate() with wake phase

## Files to Modify
- `alive_memory/consolidation/whisper.py` — enhance
- `alive_memory/consolidation/wake.py` — NEW
- `alive_memory/consolidation/__init__.py` — wire wake phase
- `tests/test_whisper.py` — enhance
- `tests/test_wake.py` — NEW
