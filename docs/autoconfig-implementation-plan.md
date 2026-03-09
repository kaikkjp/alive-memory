# AutoConfig Implementation Plan

**alive-memory SDK v0.4 — Self-Tuning Cognitive Memory**

Status: Implementation plan
Date: 2026-03-09
Based on: [autoconfig-alive-memory-spec.md](../../autoresearch-monetize/autoconfig-alive-memory-spec.md)
Pattern: [karpathy/autoresearch](https://github.com/karpathy/autoresearch)

---

## 0. Executive Summary

AutoConfig adds a `memory.autotune()` API that optimizes alive-memory's configuration
parameters through simulated conversations and automated evaluation. The system replays
scripted scenario suites against fresh memory instances, scores the results, mutates the
config, and repeats — keeping the best-scoring configuration.

This plan covers Phase 1 (hardcoded scenarios + local tuning) and Phase 2 (custom
scenarios + LLM-guided mutation). Phase 3 (continuous tuning) is explicitly deferred.

**Estimated effort:** 10-14 working days
**New code location:** `alive_memory/autotune/`
**Net-new files:** ~15
**Existing files modified:** 3 (config.py, __init__.py, pyproject.toml)

---

## 1. Prerequisites (Must Be Done First)

### 1.1 Clock Abstraction

**Problem:** The SDK uses `datetime.now(timezone.utc)` in 6+ places (thalamus.py,
formation.py, writer.py, consolidation/__init__.py, sleep.py, identity modules). The
simulator needs to advance simulated time (e.g., "3 days pass") without waiting real time.

**Solution:** Introduce a `Clock` protocol with a default `SystemClock` and a
`SimulatedClock` for autotune.

```
alive_memory/clock.py (NEW)
```

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Default clock — returns real wall time."""
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SimulatedClock:
    """Clock with manually controllable time for testing and autotune."""

    def __init__(self, start: datetime | None = None):
        self._time = start or datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self._time

    def advance(self, seconds: float) -> None:
        from datetime import timedelta
        self._time += timedelta(seconds=seconds)

    def set(self, dt: datetime) -> None:
        self._time = dt
```

**Affected files (thread the clock through):**

| File | Current usage | Change |
|---|---|---|
| `__init__.py` (AliveMemory) | N/A | Accept optional `clock` param, default `SystemClock()`, pass to intake/writer |
| `intake/thalamus.py` | `datetime.now(timezone.utc)` | Accept optional `clock` param |
| `intake/formation.py` | `datetime.now(timezone.utc)` | Accept optional `clock` param |
| `hot/writer.py` | `datetime.now(timezone.utc)` | Accept optional `clock` param |
| `consolidation/__init__.py` | Time used implicitly via moments | No change needed (uses moment timestamps) |
| `sleep.py` | `time.monotonic()` | No change (monotonic is for duration, not calendar time) |

**Rule:** Clock is always optional, defaults to `SystemClock()`. Zero breaking changes.

### 1.2 Config Parameter Coverage Audit

**Problem:** The spec lists ~20 tunable parameters, but many don't exist in the current
codebase. We must scope to parameters the engine actually responds to.

**Currently implemented parameters** (from `alive_config.yaml` + hardcoded constants):

| Parameter | Location | Current key / constant |
|---|---|---|
| Base salience | `alive_config.yaml` | `intake.base_salience` |
| Conversation boost | `alive_config.yaml` | `intake.conversation_boost` |
| Novelty weight | `alive_config.yaml` | `intake.novelty_weight` |
| Drive equilibrium pull | `alive_config.yaml` | `drives.equilibrium_pull` |
| Diminishing returns | `alive_config.yaml` | `drives.diminishing_returns` |
| Social sensitivity | `alive_config.yaml` | `drives.social_sensitivity` |
| Decay rate | `alive_config.yaml` | `consolidation.decay_rate` |
| Decay floor | `alive_config.yaml` | `consolidation.decay_floor` |
| Dream count | `alive_config.yaml` | `consolidation.dream_count` |
| Reflection count | `alive_config.yaml` | `consolidation.reflection_count` |
| Nap moment count | `alive_config.yaml` | `consolidation.nap_moment_count` |
| Cold embed limit | `alive_config.yaml` | `consolidation.cold_embed_limit` |
| Recall default limit | `alive_config.yaml` | `recall.default_limit` |
| Recall context lines | `alive_config.yaml` | `recall.context_lines` |
| Identity snapshot interval | `alive_config.yaml` | `identity.snapshot_interval` |
| Drift threshold | `alive_config.yaml` | `identity.drift_threshold` |
| EMA alpha | `alive_config.yaml` | `identity.ema_alpha` |
| Cooldown cycles | `alive_config.yaml` | `identity.cooldown_cycles` |
| Max day moments | `formation.py` | `MAX_DAY_MOMENTS = 30` (hardcoded) |
| Base salience threshold | `formation.py` | `BASE_THRESHOLD = 0.35` (hardcoded) |
| Max salience threshold | `formation.py` | `MAX_THRESHOLD = 0.55` (hardcoded) |
| Dedup window minutes | `formation.py` | `DEDUP_WINDOW_MINUTES = 30` (hardcoded) |
| Dedup similarity threshold | `formation.py` | `0.85` (hardcoded in `_is_duplicate`) |

**Action items:**
1. Promote hardcoded constants in `formation.py` to config keys (non-breaking: read from
   config with current values as defaults).
2. Do NOT create aspirational params that nothing reads (e.g. `hot_memory_ttl_seconds`,
   `cold_storage_compression_ratio`). Those can be added later when the engine supports them.
3. Final tunable parameter count: **~22** (18 existing YAML + 4 promoted from constants).

---

## 2. Architecture

### 2.1 Package Structure

```
alive_memory/
  autotune/
    __init__.py          # Public API: autotune(), AutotuneResult
    engine.py            # Main optimization loop
    mutator.py           # Config mutation strategies
    simulator.py         # Replays scenarios against AliveMemory instance
    evaluator.py         # Scoring functions + MemoryScore
    judge.py             # LLM-as-judge for subjective metrics
    report.py            # Markdown report generation
    types.py             # AutotuneResult, MemoryScore, Experiment, etc.
    profiles.py          # Preset config profiles (low-latency, high-recall, etc.)
    scenarios/
      __init__.py
      schema.py          # Scenario dataclass + YAML parser
      loader.py          # Load builtin or custom scenarios
      builtin/
        short_term_recall.yaml
        cross_session_recall.yaml
        consolidation_quality.yaml
        deduplication.yaml
        forgetting.yaml
        identity_coherence.yaml
        overload.yaml
        contradiction.yaml
  clock.py               # Clock protocol (prerequisite 1.1)
```

### 2.2 Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                    engine.autotune()                     │
│                                                         │
│  for iteration in range(budget):                        │
│    config = mutator.mutate(best_config, strategy, ...)  │
│    scores = []                                          │
│    for scenario in scenarios:                           │
│      mem = AliveMemory(fresh_db, config, SimulatedClock)│
│      result = simulator.run(mem, scenario)              │
│      score = evaluator.score(result, scenario)          │
│      scores.append(score)                               │
│    composite = evaluator.aggregate(scores)              │
│    if composite < best_composite:     # lower = better  │
│      best_config = config                               │
│      best_composite = composite                         │
│    log_experiment(iteration, config, composite)          │
│                                                         │
│  return AutotuneResult(best_config, experiment_log)      │
└─────────────────────────────────────────────────────────┘
```

### 2.3 Isolation Guarantee

Each iteration gets:
- A fresh SQLite database (in-memory or temp file)
- A fresh temp directory for hot memory files
- A fresh `AliveMemory` instance with the candidate config
- A `SimulatedClock` starting at the scenario's initial timestamp

No state leaks between iterations. This mirrors autoresearch's "same initial weights" constraint.

---

## 3. Component Specifications

### 3.1 Scenario Schema (`scenarios/schema.py`)

```python
@dataclass
class ScenarioTurn:
    role: str                        # "user", "system"
    content: str                     # Turn text (for user turns)
    action: str = "intake"           # "intake", "recall", "advance_time", "consolidate"
    simulated_time: str | None       # ISO 8601 timestamp (optional, overrides clock)
    advance_seconds: int = 0         # For advance_time action
    metadata: dict = field(...)      # Extra metadata (visitor_name, thread_id, etc.)

    # Evaluation expectations (for recall/check turns)
    expected_recall: ExpectedRecall | None = None

@dataclass
class ExpectedRecall:
    must_contain: list[str]          # Keywords that MUST appear in recall results
    must_not_contain: list[str]      # Keywords that must NOT appear
    min_results: int = 1             # Minimum number of recall hits

@dataclass
class Scenario:
    name: str
    description: str
    category: str                    # short_term, cross_session, consolidation, etc.
    turns: list[ScenarioTurn]
    setup_config: dict | None = None # Optional config overrides for this scenario
```

**YAML format:**

```yaml
name: returning_user_after_3_days
description: "User discusses project details, returns 3 days later"
category: cross_session_recall
turns:
  - role: user
    content: "I'm working on a React dashboard for Q3 metrics"
    action: intake
    simulated_time: "2026-03-01T10:00:00Z"

  - role: user
    content: "The main KPIs are MRR, churn rate, and NPS"
    action: intake
    simulated_time: "2026-03-01T10:05:00Z"

  - role: system
    action: advance_time
    advance_seconds: 259200  # 3 days

  - role: system
    action: consolidate  # trigger sleep cycle

  - role: user
    content: "What metrics was I tracking?"
    action: recall
    expected_recall:
      must_contain: ["MRR", "churn", "NPS"]
      must_not_contain: []
      min_results: 1
```

**Design decisions:**
- `advance_time` advances the SimulatedClock, does NOT trigger consolidation automatically.
  The scenario must explicitly include `consolidate` turns if it wants sleep to run.
- This keeps scenarios deterministic and testable.
- No LLM-generated agent responses in Phase 1. The simulator only runs intake/recall/
  consolidate — it doesn't simulate the agent "replying." This cuts cost from ~$24 to ~$0
  per iteration for the simulation step.

### 3.2 Simulator (`simulator.py`)

```python
@dataclass
class SimulationResult:
    """Result of running one scenario against one config."""
    scenario_name: str
    recall_results: list[RecallResult]   # One per recall turn
    consolidation_reports: list[SleepReport]
    final_state: CognitiveState
    moments_recorded: int
    moments_rejected: int                # Below salience threshold
    hot_memory_files: dict[str, str]     # subdir/filename → content snapshot
    elapsed_real_ms: int
    errors: list[str]

@dataclass
class RecallResult:
    turn_index: int
    query: str
    recall_context: RecallContext
    expected: ExpectedRecall
    elapsed_ms: int
```

**Simulator loop:**

```python
async def run_scenario(
    scenario: Scenario,
    config: AliveConfig,
    llm: LLMProvider | None = None,
    embedder: EmbeddingProvider | None = None,
) -> SimulationResult:
    clock = SimulatedClock(parse_iso(scenario.turns[0].simulated_time))

    async with AliveMemory(
        storage=":memory:",
        memory_dir=tempdir,
        config=config,
        llm=llm,
        embedder=embedder,
        clock=clock,
    ) as mem:
        for turn in scenario.turns:
            if turn.simulated_time:
                clock.set(parse_iso(turn.simulated_time))

            match turn.action:
                case "intake":
                    moment = await mem.intake(
                        event_type="conversation",
                        content=turn.content,
                        metadata=turn.metadata,
                    )
                    # track recorded vs rejected

                case "recall":
                    context = await mem.recall(turn.content)
                    # store RecallResult with expected

                case "advance_time":
                    clock.advance(turn.advance_seconds)

                case "consolidate":
                    report = await mem.consolidate(depth="full")
                    # store report

        return SimulationResult(...)
```

**Key constraint:** The simulator NEVER calls an LLM for agent responses. It only uses the
LLM for consolidation (reflection/dreaming) if one is provided. This means:
- Without LLM: intake + recall work, consolidation writes raw moments to journal (no
  reflection). Mechanical metrics only. **Cost: $0 per iteration.**
- With LLM: full consolidation with reflection + dreaming. Enables LLM-judge metrics.
  **Cost: ~$0.30-0.50 per iteration** (consolidation LLM calls only, not 8000 agent
  response calls).

### 3.3 Evaluator (`evaluator.py`)

```python
@dataclass
class MemoryScore:
    # Mechanical metrics (computed from SimulationResult, no LLM needed)
    recall_precision: float       # Of recalled items, % that were expected
    recall_completeness: float    # Of expected items, % that were recalled
    intake_acceptance_rate: float # % of intake turns that produced a DayMoment
    dedup_accuracy: float         # Correctly rejected duplicates (from dedup scenario)
    decay_accuracy: float         # Correctly forgot irrelevant items (from forgetting scenario)

    # LLM-judge metrics (optional, require LLM)
    consolidation_fidelity: float = 0.0  # Key facts preserved after consolidation
    identity_coherence: float = 0.0      # Identity consistency over time

    # Performance metrics
    recall_latency_ms: float = 0.0       # Median recall time
    consolidation_latency_ms: float = 0.0 # Consolidation time

    @property
    def composite(self) -> float:
        """Single optimization target. Lower = better."""
        quality = (
            0.30 * self.recall_completeness
            + 0.25 * self.recall_precision
            + 0.15 * self.consolidation_fidelity
            + 0.10 * self.dedup_accuracy
            + 0.10 * self.decay_accuracy
            + 0.05 * self.identity_coherence
            + 0.05 * self.intake_acceptance_rate
        )
        # Latency penalty (normalized)
        latency_penalty = min(self.recall_latency_ms / 1000.0, 1.0) * 0.05
        return 1.0 - quality + latency_penalty
```

**Mechanical scoring (no LLM):**

```python
def score_recall(result: RecallResult) -> tuple[float, float]:
    """Returns (precision, completeness) for a single recall turn."""
    expected = result.expected
    context = result.recall_context

    # Flatten all recall text into one searchable blob
    all_text = " ".join(
        context.journal_entries
        + context.visitor_notes
        + context.self_knowledge
        + context.reflections
        + context.thread_context
    ).lower()

    # Completeness: what % of must_contain keywords were found
    found = sum(1 for kw in expected.must_contain if kw.lower() in all_text)
    completeness = found / max(len(expected.must_contain), 1)

    # Precision: were there must_not_contain violations?
    violations = sum(1 for kw in expected.must_not_contain if kw.lower() in all_text)
    precision = 1.0 - (violations / max(len(expected.must_not_contain), 1)) if expected.must_not_contain else 1.0

    return precision, completeness
```

**Two-tier scoring:**
1. **Fast path (no LLM):** Only mechanical metrics. Use for keep-or-revert gate.
   If mechanical score improved → keep. If degraded → revert. No LLM cost.
2. **Judge path (with LLM):** Run LLM judge on final top-N candidates only (e.g. the
   best 3 configs found during the loop). This gives consolidation_fidelity and
   identity_coherence scores for the final report.

This is the biggest cost optimization vs. the original spec ($27 → ~$3-5).

### 3.4 Mutator (`mutator.py`)

**Tunable parameter registry:**

```python
@dataclass
class TunableParam:
    key: str                    # Config dot-notation key
    param_type: str             # "float", "int", "bool"
    min_value: float | int
    max_value: float | int
    step: float | int           # Default perturbation step
    description: str

TUNABLE_PARAMS: list[TunableParam] = [
    TunableParam("intake.base_salience", "float", 0.1, 0.9, 0.05, "Base salience for all events"),
    TunableParam("intake.conversation_boost", "float", 0.0, 0.5, 0.05, "Extra salience for conversations"),
    TunableParam("intake.novelty_weight", "float", 0.0, 0.6, 0.05, "Weight of novelty in salience"),
    TunableParam("intake.salience_threshold", "float", 0.2, 0.7, 0.05, "Base threshold for moment formation"),
    TunableParam("intake.max_day_moments", "int", 10, 100, 5, "Max moments before eviction"),
    TunableParam("intake.dedup_window_minutes", "int", 5, 120, 10, "Dedup time window"),
    TunableParam("intake.dedup_similarity", "float", 0.5, 0.99, 0.05, "Fuzzy match threshold for dedup"),
    TunableParam("drives.equilibrium_pull", "float", 0.005, 0.1, 0.005, "Drive return-to-center rate"),
    TunableParam("drives.diminishing_returns", "float", 0.5, 1.0, 0.05, "Repeated stimulus multiplier"),
    TunableParam("drives.social_sensitivity", "float", 0.1, 1.0, 0.1, "Social event drive sensitivity"),
    TunableParam("consolidation.dream_count", "int", 0, 10, 1, "Dreams per consolidation"),
    TunableParam("consolidation.reflection_count", "int", 0, 5, 1, "Reflections per consolidation"),
    TunableParam("consolidation.nap_moment_count", "int", 1, 20, 2, "Moments processed in nap"),
    TunableParam("consolidation.cold_embed_limit", "int", 10, 200, 10, "Max cold embeddings per sleep"),
    TunableParam("recall.default_limit", "int", 3, 30, 2, "Max recall results per category"),
    TunableParam("recall.context_lines", "int", 1, 10, 1, "Lines of context in grep results"),
    TunableParam("identity.drift_threshold", "float", 0.05, 0.5, 0.05, "Trait change to flag as drift"),
    TunableParam("identity.ema_alpha", "float", 0.01, 0.2, 0.01, "EMA smoothing for trait updates"),
    TunableParam("identity.cooldown_cycles", "int", 1, 20, 2, "Min cycles between drift events"),
    TunableParam("identity.snapshot_interval", "int", 3, 30, 3, "Cycles between identity snapshots"),
]
```

**Mutation strategies:**

```python
class MutationStrategy(Enum):
    SINGLE_PERTURBATION = "single_perturbation"
    CORRELATED_PAIR = "correlated_pair"
    PROFILE_SWAP = "profile_swap"
    LLM_GUIDED = "llm_guided"      # Phase 2

# Correlated pairs: params that are physically related
CORRELATED_PAIRS = [
    ("intake.base_salience", "intake.salience_threshold"),       # both affect what gets recorded
    ("intake.max_day_moments", "intake.salience_threshold"),     # capacity vs. selectivity
    ("consolidation.dream_count", "consolidation.reflection_count"),  # sleep depth
    ("recall.default_limit", "recall.context_lines"),            # recall breadth vs. depth
    ("intake.dedup_window_minutes", "intake.dedup_similarity"),  # dedup aggressiveness
]

def select_strategy(iteration: int, history: list[ExperimentRecord]) -> MutationStrategy:
    if iteration < 3:
        return MutationStrategy.PROFILE_SWAP
    if _no_improvement_in_last(history, n=5):
        return MutationStrategy.CORRELATED_PAIR  # break out of local minimum
    return MutationStrategy.SINGLE_PERTURBATION

def mutate(config: dict, strategy: MutationStrategy, ...) -> dict:
    match strategy:
        case MutationStrategy.SINGLE_PERTURBATION:
            # Pick random param, add/subtract step * random(0.5, 1.5)
            ...
        case MutationStrategy.CORRELATED_PAIR:
            # Pick random pair, adjust in complementary directions
            ...
        case MutationStrategy.PROFILE_SWAP:
            # Swap to one of the preset profiles
            ...
        case MutationStrategy.LLM_GUIDED:
            # Feed experiment history to LLM, ask for hypothesis (Phase 2)
            ...
```

### 3.5 Preset Profiles (`profiles.py`)

```python
PROFILES = {
    "default": {},  # alive_config.yaml defaults

    "high_recall": {
        "intake.base_salience": 0.35,
        "intake.salience_threshold": 0.25,
        "intake.max_day_moments": 60,
        "recall.default_limit": 20,
        "recall.context_lines": 5,
        "consolidation.cold_embed_limit": 100,
    },

    "low_noise": {
        "intake.base_salience": 0.6,
        "intake.salience_threshold": 0.5,
        "intake.max_day_moments": 15,
        "intake.dedup_similarity": 0.7,
        "recall.default_limit": 5,
    },

    "fast_consolidation": {
        "consolidation.dream_count": 1,
        "consolidation.reflection_count": 1,
        "consolidation.nap_moment_count": 3,
        "consolidation.cold_embed_limit": 20,
    },

    "deep_identity": {
        "identity.snapshot_interval": 5,
        "identity.drift_threshold": 0.08,
        "identity.ema_alpha": 0.1,
        "identity.cooldown_cycles": 3,
    },
}
```

These are the first configs tried (iterations 0-3), giving the optimizer a diverse
starting population before single-parameter perturbation begins.

### 3.6 Engine (`engine.py`)

```python
@dataclass
class AutotuneConfig:
    budget: int = 50                   # Total iterations
    scenarios: str = "builtin"         # "builtin" or path to custom dir
    scoring_weights: dict | None       # Override MemoryScore weights
    use_llm_judge: bool = False        # Enable LLM judge (Phase 2)
    llm_judge_top_n: int = 3           # Only judge the top N candidates
    seed: int = 42                     # Reproducibility
    verbose: bool = True               # Print progress
    parallel_scenarios: bool = False   # Future: run scenarios in parallel

async def autotune(
    config: AliveConfig | dict | None = None,
    *,
    autotune_config: AutotuneConfig | None = None,
    llm: LLMProvider | None = None,
    embedder: EmbeddingProvider | None = None,
) -> AutotuneResult:
    """Main optimization loop."""
    ...
```

**Experiment log** is a list of `ExperimentRecord` dataclasses, persisted as JSON:

```python
@dataclass
class ExperimentRecord:
    iteration: int
    config_snapshot: dict           # Full config dict
    config_diff: dict               # Only changed params vs. previous
    strategy: str                   # Mutation strategy used
    scores: dict[str, MemoryScore]  # Per-scenario scores
    composite: float                # Aggregate composite score
    is_best: bool                   # Was this the new best?
    elapsed_seconds: float
    timestamp: str                  # ISO 8601
```

### 3.7 Report (`report.py`)

Generates a markdown report from the experiment log:

```
# AutoConfig Tuning Report

## Summary
- Iterations: 50
- Best composite score: 0.182 (baseline: 0.341)
- Improvement: 46.6%
- Total time: 14m 23s
- LLM cost: $0.00 (mechanical scoring only)

## Best Configuration vs. Baseline

| Parameter | Baseline | Tuned | Change |
|---|---|---|---|
| intake.base_salience | 0.50 | 0.40 | -0.10 |
| intake.salience_threshold | 0.35 | 0.28 | -0.07 |
| recall.context_lines | 3 | 5 | +2 |
...

## Per-Scenario Scores

| Scenario | Baseline | Tuned | Delta |
|---|---|---|---|
| short_term_recall | 0.31 | 0.12 | -0.19 |
| cross_session_recall | 0.45 | 0.22 | -0.23 |
...

## Parameter Sensitivity (which params mattered most)

| Parameter | Times mutated | Avg score delta when changed |
|---|---|---|
| intake.salience_threshold | 12 | -0.04 (improved) |
| recall.context_lines | 8 | -0.03 (improved) |
...

## Experiment Log (last 10 iterations)
...
```

### 3.8 Public API (changes to `__init__.py`)

```python
# New imports in alive_memory/__init__.py
from alive_memory.autotune import autotune, AutotuneConfig, AutotuneResult

# New method on AliveMemory class
class AliveMemory:
    ...

    async def autotune(
        self,
        budget: int = 50,
        scenarios: str = "builtin",
        *,
        scoring_weights: dict | None = None,
        verbose: bool = True,
    ) -> AutotuneResult:
        """Run parameter auto-tuning.

        Args:
            budget: Number of iterations.
            scenarios: "builtin" or path to custom scenario directory.
            scoring_weights: Override default MemoryScore weights.
            verbose: Print progress during tuning.

        Returns:
            AutotuneResult with best_config, experiment_log, and report.
        """
        from alive_memory.autotune import autotune as _autotune, AutotuneConfig

        result = await _autotune(
            config=self._config,
            autotune_config=AutotuneConfig(
                budget=budget,
                scenarios=scenarios,
                scoring_weights=scoring_weights,
                verbose=verbose,
            ),
            llm=self._llm,
            embedder=self._embedder,
        )

        return result

    def apply_tuned_config(self, result: "AutotuneResult") -> None:
        """Apply an AutotuneResult's best config to this instance."""
        for key, value in result.best_config.items():
            self._config.set(key, value)
```

### 3.9 CLI

Add to `pyproject.toml`:

```toml
[project.scripts]
alive-memory-server = "alive_memory.server.app:main"
alive-memory-autotune = "alive_memory.autotune.cli:main"
```

```python
# alive_memory/autotune/cli.py
async def main():
    parser = argparse.ArgumentParser(description="Auto-tune alive-memory parameters")
    parser.add_argument("--budget", type=int, default=50)
    parser.add_argument("--scenarios", default="builtin")
    parser.add_argument("--output", default="autotune_result.json")
    parser.add_argument("--report", default="autotune_report.md")
    parser.add_argument("--config", help="Path to base config YAML")
    parser.add_argument("--verbose", action="store_true", default=True)
    ...
```

---

## 4. Builtin Scenarios

### 4.1 Scenario List

Each scenario is 10-30 turns, targeting one memory capability.

| # | Scenario | Category | Turns | What it tests |
|---|---|---|---|---|
| 1 | `short_term_recall` | short_term | 10 | Recall within same session, no consolidation |
| 2 | `cross_session_recall` | cross_session | 20 | Recall after time gap + consolidation |
| 3 | `consolidation_quality` | consolidation | 25 | Key facts survive sleep cycle |
| 4 | `deduplication` | dedup | 15 | Same fact stated 5 ways, should dedup |
| 5 | `forgetting` | forgetting | 20 | Chitchat shouldn't pollute recall of important info |
| 6 | `identity_coherence` | identity | 30 | Self-model stays consistent over many cycles |
| 7 | `overload` | overload | 30 | 30 facts in rapid succession, most important survive |
| 8 | `contradiction` | contradiction | 15 | Updated info overwrites stale info in recall |

### 4.2 Scenario Design Principles

1. **No LLM-generated agent responses.** Scenarios contain only user messages, time
   advances, and consolidation triggers. The memory system processes them mechanically.
2. **Every recall turn has `expected_recall`.** This is what makes scoring deterministic.
3. **Scenarios are idempotent.** Same config → same score (given same LLM, if used).
4. **Scenarios exercise different parameter groups:**
   - Short-term/overload → intake params (salience, threshold, max_day_moments)
   - Cross-session/consolidation → consolidation params (dream_count, embed_limit)
   - Dedup → dedup params (window, similarity)
   - Forgetting → salience threshold + recall limit
   - Identity → identity params (drift_threshold, ema_alpha)
   - Contradiction → recall freshness weighting

### 4.3 Example: `short_term_recall.yaml`

```yaml
name: short_term_recall
description: "User shares 5 distinct facts, then asks about each one"
category: short_term
turns:
  - role: user
    content: "My favorite programming language is Rust"
    action: intake
    simulated_time: "2026-03-01T10:00:00Z"

  - role: user
    content: "I'm building a web scraper for real estate listings"
    action: intake
    simulated_time: "2026-03-01T10:01:00Z"

  - role: user
    content: "The scraper needs to handle pagination and rate limiting"
    action: intake
    simulated_time: "2026-03-01T10:02:00Z"

  - role: user
    content: "I work at a company called Nextera in the data engineering team"
    action: intake
    simulated_time: "2026-03-01T10:03:00Z"

  - role: user
    content: "Our main database is PostgreSQL but we're evaluating DuckDB"
    action: intake
    simulated_time: "2026-03-01T10:04:00Z"

  # Now recall
  - role: user
    content: "What programming language do I prefer?"
    action: recall
    simulated_time: "2026-03-01T10:05:00Z"
    expected_recall:
      must_contain: ["Rust"]
      min_results: 1

  - role: user
    content: "What am I building?"
    action: recall
    simulated_time: "2026-03-01T10:05:30Z"
    expected_recall:
      must_contain: ["scraper", "real estate"]
      min_results: 1

  - role: user
    content: "Where do I work?"
    action: recall
    simulated_time: "2026-03-01T10:06:00Z"
    expected_recall:
      must_contain: ["Nextera"]
      min_results: 1

  - role: user
    content: "What database technologies are relevant?"
    action: recall
    simulated_time: "2026-03-01T10:06:30Z"
    expected_recall:
      must_contain: ["PostgreSQL"]
      min_results: 1
```

---

## 5. Cost Model (Revised)

The original spec estimated $27 per run. By eliminating LLM-generated agent responses
from the simulation step, costs drop dramatically:

### Phase 1 (mechanical scoring only)

| Component | Calls per iteration | Cost per iteration | 50 iterations |
|---|---|---|---|
| Simulation (intake/recall) | 0 LLM | $0 | $0 |
| Consolidation (if LLM provided) | ~8 scenarios x ~3 LLM calls | ~$0.40 | ~$20 |
| Scoring | 0 LLM | $0 | $0 |
| **Total with LLM consolidation** | | | **~$20** |
| **Total without LLM (mechanical only)** | | | **$0** |

### Phase 2 (add LLM judge for top-N)

| Component | Calls | Cost |
|---|---|---|
| LLM judge (top 3 configs x 8 scenarios x 2 judges) | 48 | ~$1.50 |
| LLM-guided mutations (5 calls) | 5 | ~$0.15 |
| **Phase 2 additional cost** | | **~$1.65** |

**Key insight:** Users can run autotune with `llm=None` for $0 cost and still get
meaningful optimization from mechanical metrics. LLM is optional for better consolidation
quality and subjective scoring.

---

## 6. Implementation Order

### Step 0: Prerequisites (Day 1-2)

- [ ] **0.1** Create `alive_memory/clock.py` with `Clock`, `SystemClock`, `SimulatedClock`
- [ ] **0.2** Thread `clock` parameter through `AliveMemory.__init__`, `intake/thalamus.py`,
  `intake/formation.py`, `hot/writer.py` (optional param, default `SystemClock()`)
- [ ] **0.3** Promote `formation.py` hardcoded constants to config-driven values:
  - `MAX_DAY_MOMENTS` → `config.get("intake.max_day_moments", 30)`
  - `BASE_THRESHOLD` → `config.get("intake.salience_threshold", 0.35)`
  - `MAX_THRESHOLD` → `config.get("intake.max_salience_threshold", 0.55)`
  - `DEDUP_WINDOW_MINUTES` → `config.get("intake.dedup_window_minutes", 30)`
  - `0.85` similarity → `config.get("intake.dedup_similarity", 0.85)`
- [ ] **0.4** Update `alive_config.yaml` with new default keys
- [ ] **0.5** Run existing tests — nothing should break

### Step 1: Types + Schema (Day 2)

- [ ] **1.1** Create `alive_memory/autotune/types.py` — all dataclasses
- [ ] **1.2** Create `alive_memory/autotune/scenarios/schema.py` — Scenario + YAML parser
- [ ] **1.3** Create `alive_memory/autotune/scenarios/loader.py` — load builtin/custom

### Step 2: Scenarios (Day 3-4)

- [ ] **2.1** Write `short_term_recall.yaml`
- [ ] **2.2** Write `cross_session_recall.yaml`
- [ ] **2.3** Write `consolidation_quality.yaml`
- [ ] **2.4** Write `deduplication.yaml`
- [ ] **2.5** Write `forgetting.yaml`
- [ ] **2.6** Write `identity_coherence.yaml`
- [ ] **2.7** Write `overload.yaml`
- [ ] **2.8** Write `contradiction.yaml`

### Step 3: Simulator (Day 5-6)

- [ ] **3.1** Create `alive_memory/autotune/simulator.py`
- [ ] **3.2** Integration test: run one scenario against default config, verify
  SimulationResult is populated correctly
- [ ] **3.3** Integration test: verify isolation (two runs with same config → same results)

### Step 4: Evaluator (Day 6-7)

- [ ] **4.1** Create `alive_memory/autotune/evaluator.py` — mechanical scoring
- [ ] **4.2** Test: score a known SimulationResult, verify scores are correct
- [ ] **4.3** Create `alive_memory/autotune/judge.py` — LLM-as-judge (stub for Phase 1,
  returns 0.0 for subjective metrics)

### Step 5: Mutator (Day 7-8)

- [ ] **5.1** Create `alive_memory/autotune/mutator.py` — param registry + strategies
- [ ] **5.2** Create `alive_memory/autotune/profiles.py` — preset profiles
- [ ] **5.3** Test: mutate a config, verify output is valid and within bounds

### Step 6: Engine (Day 8-9)

- [ ] **6.1** Create `alive_memory/autotune/engine.py` — main loop
- [ ] **6.2** Create `alive_memory/autotune/__init__.py` — public API
- [ ] **6.3** Integration test: run 5-iteration autotune with builtin scenarios
- [ ] **6.4** Verify: tuned config scores equal or better than default

### Step 7: Report + CLI (Day 9-10)

- [ ] **7.1** Create `alive_memory/autotune/report.py` — markdown generation
- [ ] **7.2** Create `alive_memory/autotune/cli.py`
- [ ] **7.3** Update `pyproject.toml` with new CLI entry point
- [ ] **7.4** Update `alive_memory/__init__.py` — add `autotune()` method to AliveMemory

### Step 8: Testing + Polish (Day 10-12)

- [ ] **8.1** Full test suite for autotune package
- [ ] **8.2** Run 50-iteration autotune against default config — verify improvement
- [ ] **8.3** Performance: verify 50 iterations complete in < 30 minutes (mechanical) or
  < 2 hours (with LLM consolidation)
- [ ] **8.4** Edge cases: empty scenarios, broken YAML, missing LLM, etc.

### Step 9: Phase 2 additions (Day 12-14, if time permits)

- [ ] **9.1** LLM-guided mutation strategy in `mutator.py`
- [ ] **9.2** LLM judge implementation in `judge.py`
- [ ] **9.3** Custom scenario directory support in `loader.py`
- [ ] **9.4** Parameter sensitivity analysis in `report.py`

---

## 7. Testing Strategy

### Unit Tests

| Test file | What it tests |
|---|---|
| `tests/test_clock.py` | SimulatedClock advance/set |
| `tests/test_autotune_schema.py` | Scenario YAML parsing |
| `tests/test_autotune_evaluator.py` | Mechanical scoring |
| `tests/test_autotune_mutator.py` | Mutation strategies, bounds checking |
| `tests/test_autotune_profiles.py` | Profile loading |

### Integration Tests

| Test file | What it tests |
|---|---|
| `tests/test_autotune_simulator.py` | Full scenario replay, isolation |
| `tests/test_autotune_engine.py` | 3-iteration autotune end-to-end |
| `tests/test_autotune_report.py` | Report generation from experiment log |

### Validation Test (manual, not CI)

Run full 50-iteration autotune and verify:
- Best config scores >=15% better than default (success criterion from spec)
- No config parameter hits bounds on all iterations (would indicate bounds are too tight)
- Report is readable and useful

---

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Clock threading breaks existing tests | High | Clock is always optional with SystemClock default. All existing code paths unchanged. Run full test suite after step 0. |
| Scenarios don't exercise real-world patterns | Medium | Scenarios designed from actual Shopkeeper conversation patterns. Phase 2 adds custom scenarios. |
| Recall scoring is too coarse (keyword match) | Medium | This is intentionally simple for Phase 1. Phase 2 adds LLM judge for nuance. |
| Optimizer finds a fragile config | Medium | Hold out 2 scenarios for validation (score on 6, validate on 2). Report both scores. |
| Config changes in formation.py break existing behavior | Low | New config keys use current hardcoded values as defaults. Existing behavior is identical if no config is passed. |
| Autotune is too slow | Low | Mechanical-only mode has no LLM latency. 50 iterations x 8 scenarios = 400 simulations, each takes < 1s with in-memory SQLite. |

---

## 9. What This Plan Does NOT Cover (Explicit Deferrals)

1. **Phase 3 (Continuous Tuning)** — Real conversation log replay, drift detection,
   A/B testing. This is a separate feature with different architecture requirements.
   Deserves its own spec.

2. **Prompt template tuning** — Optimizing the LLM prompts used in consolidation
   (reflection, dreaming). This crosses into AutoPrompt territory and is a separate
   optimization surface.

3. **Multi-objective Pareto optimization** — The spec mentions this as an open question.
   Phase 1 uses a single composite score. Multi-objective can be added later by exposing
   the weight vector.

4. **Transfer learning across deployments** — Aggregating tuning results across users.
   Privacy-sensitive, requires separate design.

5. **Aspirational parameters** — `hot_memory_ttl_seconds`, `cold_storage_compression_ratio`,
   `warm_to_cold_threshold`, etc. These will be added to the tunable registry when the
   engine code that reads them is implemented.

---

## 10. Success Criteria

Phase 1 is done when:

- [ ] `memory.autotune(budget=50)` runs end-to-end with mechanical scoring
- [ ] Tuned config scores >=15% better than default on builtin scenarios
- [ ] 50-iteration run completes in < 30 minutes (no LLM)
- [ ] `alive-memory-autotune` CLI works
- [ ] Markdown report is generated and readable
- [ ] All existing tests still pass
- [ ] New test coverage for autotune package

Phase 2 is done when:

- [ ] Custom scenario YAML directory is loadable
- [ ] LLM-guided mutation produces non-trivial hypotheses
- [ ] LLM judge scores correlate with mechanical scores (sanity check)
- [ ] Parameter sensitivity analysis appears in report

---

*End of implementation plan.*
