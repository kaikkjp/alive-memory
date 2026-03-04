# Architecture

## System Overview

alive-memory is a three-tier cognitive memory layer for persistent AI characters.

| Tier | Name | Storage | Accessed During | Purpose |
|------|------|---------|-----------------|---------|
| 1 | Day Memory | SQLite `day_memory` | `intake()` | Ephemeral salient moments, salience-gated |
| 2 | Hot Memory | Markdown files on disk | `recall()` | Journal, visitors, reflections, self-knowledge |
| 3 | Cold Memory | SQLite `cold_embeddings` | `consolidate()` | Vector archive for historical echoes |

## Sleep Cycle

The `sleep_cycle()` orchestrator chains six phases in order. Each phase is
fault-tolerant by default — errors are caught, logged, and collected in the
`SleepCycleReport`.

```
sleep_cycle()
├─ 1. Whisper        (config changes → dream perceptions)
├─ 2. Consolidation  (moments → reflect → journal → cold embed)
├─ 3. Meta-review    (trait stability, self-mod revert)
├─ 4. Meta-controller (metric-driven parameter homeostasis)
├─ 5. Identity       (drift detection → evaluate → apply)
└─ 6. Wake           (thread lifecycle, pool cleanup, drive reset)
```

The lightweight `nap()` variant runs only the consolidation phase in
`"nap"` depth mode — no meta, no identity, no wake.

## Provider Interfaces

Optional providers allow applications to plug into sleep phases. If a
provider is not supplied, the corresponding phase is skipped.

| Provider | Used By | Purpose |
|----------|---------|---------|
| `metrics_provider` | Meta-controller | Supplies `collect_metrics()` for parameter homeostasis |
| `drive_provider` | Meta-review | Provides drive state for trait stability checks |
| `wake_hooks` | Wake | Application-specific wake transition callbacks |
| `correction_provider` | Meta-review | Supplies correction suggestions |

## Data Flow

```
Events → intake() → DayMoment (Tier 1)
                         │
                    sleep_cycle()
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    Whisper         Consolidation    Meta-controller
  (dream text)    (reflect/journal)  (param adjust)
                      │    │
                      ▼    ▼
               Hot Memory  Cold Archive
               (Tier 2)    (Tier 3)
                                │
                         Identity Evolution
                         (drift → decide)
                                │
                              Wake
                         (cleanup/reset)
```

## Nap vs Full Sleep

| Feature | `nap()` | `sleep_cycle()` (full) |
|---------|---------|----------------------|
| Consolidation | Top N by salience | All unprocessed moments |
| Cold search | No | Yes |
| Dreaming | No | Yes |
| Cold embedding | No | Yes |
| Whisper | No | Yes (if whispers provided) |
| Meta-review | No | Yes (if drive_provider given) |
| Meta-controller | No | Yes (if metrics_provider given) |
| Identity evolution | No | Yes |
| Wake transition | No | Yes (if wake_hooks given) |
| Day memory flush | No | Yes |
