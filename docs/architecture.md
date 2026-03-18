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

## Design Gaps (2026-03-15)

Analysis of implementation vs intended design, validated against shopkeeper
production data (22 days, 3,227 cycles, $10.38 total cost) and longmemeval
benchmark results (6.8% accuracy, 83% "I don't know" responses).

### Gap 1: Hot Memory grows unbounded (should be bounded and refined)

**Intended:** Hot memory is like working memory — small, bounded, constantly
rewritten. Each sleep cycle, the LLM reads recent events + current hot memory
and *rewrites* hot as a distilled summary. Small enough to dump entirely into
the LLM context window every time. Gets sharper over time.

**Actual:** Hot memory is append-only markdown files that grow forever.
`MemoryWriter` only appends (append_journal, append_reflection, etc.).
The only rewrite method is `write_self_file()` (identity). The shopkeeper
accumulated 311 files / ~200K tokens over 22 days. Nothing is ever pruned
or refined.

### Gap 2: Cold Memory should be the raw archive (not just embeddings)

**Intended:** Cold memory stores ALL raw events permanently — the complete
archive. It's the source of truth. Searchable when the agent needs deep
history, but not loaded by default.

**Actual:** Cold memory only stores embedding vectors + content strings in
`cold_embeddings`. Raw events go to `day_memory` (SQLite) temporarily, then
get flushed after sleep (`flush_day_memory()`). The original events are
effectively lost. Cold is used only as "echoes" during the next sleep cycle
and is never queried during recall.

### Gap 3: Recall keyword grep fails on real benchmarks

**Intended:** Hot memory is small enough to dump into context (no search
needed). For deep history, cold memory provides semantic search.

**Actual:** Recall searches hot memory via substring keyword matching
(`any(kw in line_lower for kw in keywords)`). On the longmemeval benchmark
this produces 6.8% accuracy — 83% of answers are "I don't know" because
grep can't find the relevant content.

The problem: questions use different words than the stored facts.
"What store did I shop at?" greps for `["store", "shop"]` but the answer
`"Target"` doesn't contain those words. Totem search has the same keyword
limitation — `search_totems("What store did I shop at?")` won't find an
entity named `"Target"`.

**Fix:** Embed totems at creation time (during sleep, ~$0.0002 for 500
totems). At query time, embed the question and cosine-match against the
totem index. Totems are small (hundreds, not thousands) so brute-force
cosine is instant. This gives semantic retrieval over structured facts
for essentially zero cost.

### Gap 4: Salience gating is identity-blind and misplaced

**Intended:** Salience scoring should be relative to the agent's identity.
A shopkeeper cares about customer interactions; a founder agent cares about
product/hiring/metrics. The host framework already calls an LLM every waking
cycle — salience can piggyback on that call via `metadata={"salience": ...}`.

**Actual:** Salience is a deterministic heuristic with no knowledge of who
the agent is. It scores: event type base (0.15–0.40) + drive delta (0–0.20) +
content richness (0–0.20) + mood extremes (0–0.15). A shopkeeper and a
founder score identical events the same way.

Salience only acts as a gate for day memory — it decides whether a moment
is recorded, not how it's processed. Given that consolidation costs ~$0.005/day
(shopkeeper data: 7 reflect calls/day) and day memory storage is free (SQLite),
the artificial limits (`MAX_DAY_MOMENTS = 30`, `BASE_THRESHOLD = 0.35`) aren't
protecting any real budget. A $1/day budget allows ~95 consolidation cycles.

### Gap 5: Day memory is correctly a passive buffer

Day memory correctly acts as a write-mostly intake buffer between sleep
cycles. The role is right. The issue is upstream (identity-blind gating
with artificial limits) and downstream (append-only hot memory instead of
bounded refinement).

### Cost Model (from shopkeeper production data)

| Job | Shopkeeper actual/day | $1/day budget allows |
|---|---|---|
| Waking cortex | $0.08–0.61 (model-dependent) | Framework's cost |
| Consolidation (reflect) | ~$0.005 | ~$0.95 (190x headroom) |
| Embeddings (not used) | $0 | ~50K events at $0.02/M tok |

### Summary: Intended vs Actual Data Flow

**Intended:**
```
Events → day memory (buffer, everything in)
              ↓ sleep
         LLM reads day + current hot + cold echoes
              ↓
         Rewrites hot (bounded, refined, identity-scored)
         Archives raw events to cold (permanent)
         Flushes day memory
```

**Actual:**
```
Events → heuristic salience gate → day memory (max 30)
              ↓ sleep
         LLM reflects per moment → appends to hot (unbounded)
         Extracts totems + traits → SQLite (good, but keyword-only recall)
         Embeds to cold (vectors only, not raw archive)
         Flushes day memory (raw events lost)
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
