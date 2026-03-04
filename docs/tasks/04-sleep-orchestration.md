# Task: Create Full Sleep Orchestration + Update Docs

## Goal
Create `alive_memory/sleep.py` (or `alive_memory/sleep/`) as the top-level sleep cycle orchestrator, and update all SDK documentation.

## Prerequisite
Tasks 01 (meta), 02 (identity), and 03 (whispers/wake) must be merged first.

## Source (Shopkeeper — reference only)
`engine/sleep/__init__.py` (191L) — orchestrates full nightly cycle:
1. Deference check (skip if engaged)
2. Whisper phase (config changes → dream perceptions)
3. Consolidation (moment reflection → journal → daily summary)
4. Meta-review (trait stability, self-mod revert, auto-promote)
5. Evaluation (closed-loop feedback on pending experiments)
6. Meta-controller (metric-driven parameter homeostasis)
7. Identity evolution (drift detection → three-tier resolution)
8. Wake transition (threads → pool → drives → embed → flush)

Each phase is fault-tolerant (non-fatal exceptions, continue to next phase).

## What to Create

### 1. `alive_memory/sleep.py` — Top-Level Orchestrator
```python
@dataclass
class SleepConfig:
    """Configuration for the full sleep cycle."""
    enable_meta_review: bool = True
    enable_meta_controller: bool = True
    enable_identity_evolution: bool = True
    enable_wake: bool = True
    fault_tolerant: bool = True  # continue on phase failure

@dataclass
class SleepReport:
    """Results from a complete sleep cycle."""
    moments_consolidated: int
    journal_entries_written: int
    dreams_generated: int
    experiments_evaluated: int
    parameters_adjusted: int
    drift_detected: bool
    evolution_decisions: list  # EvolutionDecision
    wake_completed: bool
    errors: list[str]  # non-fatal errors if fault_tolerant
    duration_seconds: float

async def sleep_cycle(
    storage: BaseStorage,
    writer: MemoryWriter,
    reader: MemoryReader,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    config: AliveConfig,
    # Optional providers (apps supply these)
    metrics_provider: MetricsProvider | None = None,
    drive_provider: DriveProvider | None = None,
    wake_hooks: WakeHooks | None = None,
    correction_provider: CorrectionProvider | None = None,
    # Config
    sleep_config: SleepConfig | None = None,
) -> SleepReport:
    """Run a complete sleep cycle."""
    ...
```

### 2. Phase Orchestration
Each phase runs in order, errors are caught if fault_tolerant:
1. **Whisper** — `process_whispers()` from consolidation
2. **Consolidation** — `consolidate(depth="full")` from consolidation
3. **Meta-review** — `run_meta_review()` from meta (if drive_provider given)
4. **Evaluation** — `evaluate_experiment()` from meta (if metrics_provider given)
5. **Meta-controller** — `run_meta_controller()` from meta (if metrics_provider given)
6. **Identity evolution** — drift detection → evaluate → apply from identity
7. **Wake** — `run_wake_transition()` from consolidation/wake (if wake_hooks given)

### 3. Nap Variant
```python
async def nap(
    storage: BaseStorage,
    writer: MemoryWriter,
    reader: MemoryReader,
    llm: LLMProvider,
    config: AliveConfig,
) -> SleepReport:
    """Lightweight mid-cycle consolidation (no meta, no identity, no wake)."""
    return await sleep_cycle(
        storage=storage, writer=writer, reader=reader, llm=llm,
        config=config, embedder=None,
        sleep_config=SleepConfig(
            enable_meta_review=False,
            enable_meta_controller=False,
            enable_identity_evolution=False,
            enable_wake=False,
        ),
    )
```

### 4. Update Documentation

#### `docs/architecture.md` — Update with:
- Sleep cycle diagram (phases in order)
- Provider interfaces diagram
- Data flow: moments → consolidation → meta → identity → wake

#### `docs/sleep-guide.md` — NEW:
- How to integrate sleep_cycle() into your app
- Provider implementation examples
- Configuration options
- Nap vs full sleep
- Error handling and fault tolerance

#### `README.md` — Update:
- Add sleep cycle to feature list
- Add quick-start example for sleep
- Update API reference section

#### `CHANGELOG.md` — Update:
- v0.3.0: Full sleep cycle orchestration, meta-cognition, identity evolution

## Tests
- Integration: Full sleep_cycle() with all providers mocked
- Integration: sleep_cycle() with only required params (no optional providers)
- Integration: Nap variant
- Test fault tolerance: one phase fails, rest continue
- Test SleepReport aggregation

## Files to Create/Modify
- `alive_memory/sleep.py` — NEW (orchestrator)
- `alive_memory/__init__.py` — export sleep_cycle, nap
- `docs/architecture.md` — update
- `docs/sleep-guide.md` — NEW
- `README.md` — update
- `CHANGELOG.md` — update
- `tests/test_sleep_cycle.py` — NEW
