# Plan: Rebuild alive-memory SDK to Three-Tier Architecture

## Context

The alive-memory SDK was extracted from the shopkeeper engine but the extraction flattened the original three-tier memory architecture (day/hot/cold) into a single `memories` table with a strength float. This loses the structural separation that defines the shopkeeper's cognitive design. We need to rebuild the SDK to match the real architecture.

## Status: Tiers Exist But Roles Are Wrong (2026-03-15)

The three-tier structure has been implemented but behavior diverges from the
intended design. See `docs/architecture.md § Design Gaps` for the full
analysis with production data. Key issues:
1. Hot memory grows unbounded (should be bounded + rewritten each sleep)
2. Cold memory is embeddings-only (should be the raw event archive)
3. Salience gating is identity-blind (should score against agent identity)
4. Recall keyword grep gets 6.8% accuracy on longmemeval (83% "I don't know")
5. Totems exist but use keyword search (should embed for semantic retrieval)

The next iteration should fix the **roles** of each tier, not the tier
boundaries.

## The Three Tiers

**Tier 1 — Day Memory (ephemeral SQLite)**
- Records only *salient* moments, not every event
- Deterministic salience scoring (no LLM): event type base + drive delta + content richness + mood extremes
- Dynamic threshold (0.35→0.55 as count approaches MAX=30), dedup guard (30min window), lowest-salience eviction
- Flushed after full sleep processes them

**Tier 2 — Hot Memory (markdown files on disk)**
- `memory/journal/`, `visitors/`, `threads/`, `reflections/`, `self/`, `collection/`
- MemoryWriter: append_journal, append_visitor, append_reflection, append_thread, write_self_file
- MemoryReader: grep_memory (keyword search over MD files), read_visitor, read_recent_journal, read_self_knowledge
- **PRIMARY recall mechanism** — markdown-first grep, not vector search

**Tier 3 — Cold Memory (vector archive)**
- Embeddings table in SQLite (brute-force cosine, sqlite-vec optional)
- Populated during sleep only (batch embed, 50/cycle)
- Searched during sleep only for "cold echoes" — connecting today's moments to older memories
- NOT used for real-time recall

## Implementation Steps

### Step 1: Types + Storage Schema
- Add `DayMoment`, `SleepReport`, `RecallContext` to `alive_memory/types.py`
- Update `storage/base.py`: replace flat memory CRUD with `record_moment`, `get_unprocessed_moments`, `mark_moment_processed`, `flush_day_memory`, `store_cold_embedding`, `search_cold`
- Rewrite `storage/sqlite.py`: drop `memories` table, add `day_memory` + `cold_embeddings` tables. Keep all state tables (drives, mood, cognitive_state, self_model, parameters, etc.)

### Step 2: Hot Memory (new `alive_memory/hot/` package)
- `hot/writer.py` — MemoryWriter class (~200 lines): creates directory structure, append-only writes to MD files
- `hot/reader.py` — MemoryReader class (~180 lines): grep-based keyword search, read_visitor, read_recent_journal, read_self_knowledge

### Step 3: Intake Rework
- Rewrite `intake/formation.py`: `form_memory()` → `form_moment()`. Returns `DayMoment | None` (None if below threshold). Adds salience scoring, dynamic threshold, dedup guard, eviction.
- Keep thalamus.py, affect.py, drives.py as-is (they're reusable)

### Step 4: Recall Rework
- Rewrite `recall/hippocampus.py`: vector-search-over-flat-table → markdown-first grep via MemoryReader. Returns `RecallContext` (journal entries, visitor notes, self-knowledge, etc.)
- Simplify `recall/weighting.py` and `recall/context.py`

### Step 5: Consolidation Rework (biggest change)
- **Delete**: `strengthening.py`, `decay.py`, `merging.py`, `pruning.py` (flat-model artifacts)
- **Create**: `consolidation/cold_search.py` (find cold echoes during sleep), `consolidation/memory_updates.py` (apply LLM reflection outputs to hot memory)
- **Rewrite** `consolidation/__init__.py`: new sleep pipeline:
  1. Get unprocessed day_memory moments
  2. Per moment: gather hot context → cold search (full only) → LLM reflect → write journal MD → apply memory_updates → mark processed
  3. Write daily summary → batch embed to cold → flush day_memory
- **Rewrite** `dreaming.py` (recombine DayMoments + cold echoes), `reflection.py` (per-moment LLM reflection)
- Nap mode: top N moments, no cold search, marks `nap_processed=1`

### Step 6: Public API
- Rewrite `alive_memory/__init__.py` (AliveMemory class):
  - Add `memory_dir` parameter, initialize MemoryWriter + MemoryReader
  - `intake()` returns `DayMoment | None` instead of `Memory`
  - `recall()` returns `RecallContext` instead of `list[Memory]`
  - `consolidate()` returns `SleepReport` instead of `ConsolidationReport`
  - Expose `writer` and `reader` properties
- Update config defaults in `alive_config.yaml`

### Step 7: Adapters + Tests
- Update `benchmarks/adapters/alive_adapter.py` for new API
- Update `adapters/langchain.py` for new return types
- Update `server/routes.py` and `server/models.py`
- Rewrite tests: storage tests, intake tests, recall tests, consolidation tests, full integration

## Files Changed

| Action | Files |
|--------|-------|
| **CREATE** | `alive_memory/hot/__init__.py`, `hot/writer.py`, `hot/reader.py`, `consolidation/cold_search.py`, `consolidation/memory_updates.py` |
| **MAJOR REWRITE** | `storage/sqlite.py`, `intake/formation.py`, `recall/hippocampus.py`, `consolidation/__init__.py`, `consolidation/dreaming.py`, `consolidation/reflection.py`, `alive_memory/__init__.py`, `tests/test_alive_memory.py` |
| **DELETE** | `consolidation/strengthening.py`, `consolidation/decay.py`, `consolidation/merging.py`, `consolidation/pruning.py` |
| **MINOR MODIFY** | `types.py`, `storage/base.py`, `recall/weighting.py`, `recall/context.py`, `consolidation/whisper.py`, `adapters/langchain.py`, `server/routes.py`, `server/models.py`, `benchmarks/adapters/alive_adapter.py` |

~2,000 lines added, ~1,300 removed. Net +700 lines.

## Verification

1. `cd /Users/chulu/AI/alive-sdk && .venv/bin/pytest` — all tests pass
2. Smoke test: intake 100 events → verify day_memory records only salient ones → verify MD files created → consolidate → verify journal reflections written → verify cold embeddings added
3. Benchmark: `python -m benchmarks run --stream research_assistant_10k --systems alive --max-cycles 1000` still works with updated adapter
