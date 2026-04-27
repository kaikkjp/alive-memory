# Architecture

## System Overview

alive-memory is a three-tier cognitive memory layer for persistent AI
characters, positioned as autobiographical, identity-preserving, emotionally
weighted memory for persistent agents.

| Tier | Name | Storage | Accessed During | Purpose |
|------|------|---------|-----------------|---------|
| 1 | Day Memory | SQLite `day_memory` | `intake()` | Ephemeral salient moments, salience-gated |
| 2 | Hot Memory | Markdown files on disk | `recall()` | Journal, visitors, reflections, self-knowledge |
| 3 | Cold Memory | SQLite `cold_embeddings` | `consolidate()` | Vector archive for historical echoes |

## Always-On Agent Requirements

For long-running human-like agents, memory quality is measured by durable
continuity: stable identity, stable tastes, emotional salience, person
boundaries, and current facts. The current architecture has the right
primitives, but production integrations must satisfy these requirements:

| Requirement | Why It Matters | Current Risk |
|-------------|----------------|--------------|
| Durable hot memory path | Journal, reflections, visitor notes, and self files carry autobiographical continuity | `memory_dir` defaults to a temporary directory unless the caller passes one |
| Stable identity metadata | Preferences and traits need attribution to the correct visitor and session | Plain `intake()` has no default `visitor_id`, `session_id`, role, or turn index |
| Current trait state | Human tastes change; old preferences must not compete equally with new corrections | Visitor traits are append-only observations ordered mostly by confidence/recency |
| Self-model update loop | Agent identity should evolve from observed behavior, not only manual calls | `SelfModelManager` is available, but normal sleep does not derive self traits by default |
| Scoped recall | Alice's preferences must not leak into Bob's answer context | Direct visitor lookup exists, but global totem/trait search still runs afterward |
| Temporal recall | "What changed?", "before/after", and "first/last" are core continuity questions | Timestamps are stored but not first-class query constraints |
| Confidence and abstention | A human-like agent should know when it does not know | Recall returns context, but no calibrated confidence or abstention signal |
| Scalable cold search | Always-on agents accumulate large archives | Cold search currently scans SQLite rows in Python |

These are not optional polish items. They are the difference between a memory
system that can demo well and one that can keep a believable identity over
months of use.

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

## Proof Standard

To prove alive-memory is better than alternatives, compare it against
baseline systems under the same ingestion stream, token budget, embedding
model, answer model, latency budget, and storage budget. A claim should not
rest on anecdotes or a single public benchmark.

Minimum comparison set:

- No memory
- Full recent context
- Vector RAG over raw turns
- Summary memory
- Mastra Observational Memory or equivalent observation-log memory
- Mem0 or equivalent fact extraction memory
- Zep/Graphiti or equivalent temporal graph memory
- Hindsight or equivalent large-scale multi-strategy retrieval memory
- Letta/MemGPT or equivalent agent-managed memory
- alive-memory with the same LLM and embedding budget

Minimum scorecard:

- factual recall accuracy and F1
- cross-session recall
- temporal reasoning
- contradiction/currentness handling
- entity/person confusion
- identity consistency
- taste/preference consistency
- abstention/hallucination rate
- recall latency at p50/p95/p99
- storage and LLM cost

Promotion rule: alive-memory only wins if it improves the product-specific
metrics that matter for always-on agents without losing unacceptable ground
on factual recall, cost, or latency.
