# 07 — Consolidation & Storage Improvement Plan

**Date**: 2026-03-19
**Branch**: `consolidate-improvement`
**Goal**: Fix storage waste, strengthen provenance, prepare for recall overhaul

---

## Architecture Context

### What PR #21 Established
- `cold_memory` stores `moment.content` (raw DayMoment text) for event entries — not reflection text
- Unified cold archive with `entry_type` discrimination (`event`, `totem`, `trait`)
- With benchmark config `salience_threshold: 0.0`, all content becomes a DayMoment and survives in cold_memory
- The 37.4% LongMemEval score was achieved WITH all raw content preserved — the bottleneck is retrieval and assembly, not storage loss

### Current Write Map (per moment during consolidation)

| # | Content | Destination | Search method |
|---|---------|-------------|---------------|
| 1 | Reflection text (2-4 sentences) | `journal/*.md` | keyword grep |
| 2 | Reflection text (same) | `visitors/*.md` | keyword grep (duplicate) |
| 3 | Reflection text (same) | `threads/*.md` | keyword grep (duplicate) |
| 4 | Reflection text (same) | `{dynamic}/*.md` | keyword grep (duplicate) |
| 5 | Totem entity+context | `totems` table | keyword LIKE |
| 6 | Totem short text + embedding | `cold_memory` (totem) | vector search |
| 7 | Trait key+value | `visitor_traits` table | keyword LIKE |
| 8 | Trait short text + embedding | `cold_memory` (trait) | vector search |
| 9 | Raw moment.content + embedding | `cold_memory` (event) | vector search |
| 10 | Raw moment.content + embedding | `cold_embeddings` | vector search (legacy duplicate) |
| 11 | Daily summary | `reflections/*.md` | keyword grep |
| 12 | Dreams (random fragments) | `SleepReport` only | not persisted |

**Redundancies**: #2-4 duplicate #1. #6 duplicates info in #9. #8 duplicates info in #9. #10 duplicates #9.

---

## Storage Decisions

### S1: Drop `cold_embeddings` Table

`cold_embeddings` is a full duplicate of `cold_memory` event entries — same content, same embedding blob. `cold_memory` has richer columns (entry_type, visitor_id, weight, category).

**Changes**:
- `consolidation/__init__.py` — remove `store_cold_embedding()` call (lines 219-229)
- `consolidation/cold_search.py` — switch `find_cold_echoes()` from `search_cold()` to `search_cold_memory()`
- `storage/sqlite.py` — deprecate `store_cold_embedding()`, `search_cold()`, `count_cold_embeddings()`
- Add migration: `ALTER TABLE cold_embeddings RENAME TO cold_embeddings_deprecated` (or drop)

---

### S2: Stop Embedding Totems/Traits into cold_memory

Totem and trait embeddings in cold_memory are decontextualized fragments (`"favorite_food: sushi"`) of information that already exists in the raw event embedding. The relational tables (`totems`, `visitor_traits`) handle structured keyword lookup. The event embedding handles semantic search. The short-form totem/trait embeddings serve neither purpose well and cost extra embedding API calls.

Totems and traits are **derived secondary memory, not ground truth**. They're useful for structured lookup and personalization but should not be treated as the primary evidence layer.

**Changes**:
- `consolidation/fact_extraction.py` — remove `store_cold_memory()` calls for totems (lines 100-113) and traits (lines 150-164)
- Remove `embedder` parameter from `write_extracted_facts()` signature

---

### S3: Hot Memory — Write Once, Reference

The same LLM reflection text currently goes to journal + visitor + thread + dynamic category (2-4 copies). This creates fake evidence strength during grep recall and pollutes retrieval with duplicates.

**New policy**:
- **Journal**: full reflection text (canonical hot narrative)
- **Visitor**: one-line destination-specific note or reference
- **Thread**: one-line reference with timestamp + moment_id
- **Dynamic category**: one-line index entry

**Reference format example**:
```markdown
# visitors/alice.md
### 2026-03-19 14:23
Preference update — see journal [8f2c1d4a]

# threads/thread-123.md
### 2026-03-19 14:23
User clarified budget — see journal [8f2c1d4a]

# categories/preferences.md
## 14:23
[8f2c1d4a] budget preference updated
```

**Changes**:
- `consolidation/memory_updates.py` — `apply_reflection_to_hot_memory()`:
  - Keep full text write to journal (unchanged)
  - Change visitor/thread/dynamic to write short reference + optional one-line summary
- `consolidation/reflection.py` — optionally ask LLM to produce per-destination one-liners alongside the full reflection
- `hot/reader.py` — grep will now hit references; recall may need to follow the pointer to journal for full text

---

### S4: Rewrite Dreaming as Cross-Temporal Synthesis

Current `dreaming.py` generates random poetic free-association at temperature 0.9 from arbitrary fragments, then discards the output. This serves no functional purpose.

**Correct design**:
1. Pick top 3-5 moments by salience from the day
2. For each, search cold_memory for related older memories (cold echoes)
3. Assemble today's highlights + historical echoes into a combined context
4. LLM reflects on the combined picture — producing cross-temporal insights
5. **Persist** the output to `reflections/` or a dedicated `dreams/` subdir

This creates high-value cross-session connections that directly help multi-session reasoning.

**Changes**:
- `consolidation/dreaming.py` — full rewrite
- `consolidation/__init__.py` — wire new dreaming output to hot memory persistence

---

### S5: Promote session_id to cold_memory Column

`session_id` is currently buried in the `metadata` JSON blob — not indexed, not queryable by SQL. Session/thread scoping is too fundamental for JSON metadata.

**New columns on cold_memory**:
```sql
ALTER TABLE cold_memory ADD COLUMN session_id TEXT;
ALTER TABLE cold_memory ADD COLUMN turn_index INTEGER;
ALTER TABLE cold_memory ADD COLUMN role TEXT;

CREATE INDEX IF NOT EXISTS idx_cold_memory_session ON cold_memory(session_id);
CREATE INDEX IF NOT EXISTS idx_cold_memory_session_time ON cold_memory(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_cold_memory_session_type ON cold_memory(session_id, entry_type, created_at);
```

**Changes**:
- `storage/migrations/005_cold_memory_session.sql` — ALTER + indexes
- `storage/sqlite.py` — populate new columns in `store_cold_memory()`
- `consolidation/__init__.py` — pass session_id/turn_index/role from moment metadata
- Backfill script: extract session_id from existing `metadata` JSON into new column

---

### S6: Strengthen Totem/Trait Provenance (Step 1)

Make `source_moment_id` the mandatory provenance anchor. Add temporal metadata.

**New columns on totems**:
```sql
ALTER TABLE totems ADD COLUMN source_session_id TEXT;
ALTER TABLE totems ADD COLUMN source_turn_id TEXT;
ALTER TABLE totems ADD COLUMN first_seen_at TEXT;
ALTER TABLE totems ADD COLUMN last_seen_at TEXT;

CREATE INDEX IF NOT EXISTS idx_totems_source_moment ON totems(source_moment_id);
```

**New columns on visitor_traits**:
```sql
ALTER TABLE visitor_traits ADD COLUMN source_session_id TEXT;
ALTER TABLE visitor_traits ADD COLUMN source_turn_id TEXT;
ALTER TABLE visitor_traits ADD COLUMN first_seen_at TEXT;
ALTER TABLE visitor_traits ADD COLUMN last_seen_at TEXT;

CREATE INDEX IF NOT EXISTS idx_traits_source_moment ON visitor_traits(source_moment_id);
```

**Provenance rules**:
- `source_moment_id` is REQUIRED on all derived fact rows — not best-effort
- Exactly 1 cold_memory event row per `source_moment_id` (guaranteed)
- Provenance chain: `event/moment → cold_memory event → totems/traits/reflections`
- Helper APIs: `get_event_by_source_moment_id()`, `get_facts_by_source_moment_id()`

**Step 2 (designed, implement later)**:
```sql
-- Future versioning columns
ALTER TABLE visitor_traits ADD COLUMN valid_from TEXT;
ALTER TABLE visitor_traits ADD COLUMN valid_to TEXT;
ALTER TABLE visitor_traits ADD COLUMN supersedes_id TEXT;
ALTER TABLE visitor_traits ADD COLUMN status TEXT DEFAULT 'current';
-- Same for totems
```

---

### S7: source_moment_id Indexing Everywhere

Ensure provenance joins are cheap across all tables.

```sql
-- Already have on totems: idx_totems_source_moment
-- Already have on visitor_traits: idx_traits_source_moment
-- Add to cold_memory:
CREATE INDEX IF NOT EXISTS idx_cold_memory_source ON cold_memory(source_moment_id);
```

---

## Implementation Order

| Step | What | Depends on | Effort |
|------|------|-----------|--------|
| S1 | Drop cold_embeddings | — | Small |
| S2 | Stop totem/trait embedding | — | Small |
| S5 | Promote session_id | — | Small |
| S7 | source_moment_id indexes | — | Trivial |
| S6 | Totem/trait provenance columns | S7 | Small |
| S3 | Hot memory write-once | — | Medium |
| S4 | Rewrite dreaming | — | Medium |

S1, S2, S5, S7 are independent and can be done in parallel. S3 and S4 are independent of each other but each require more thought in the reflection/memory_updates code.

---

## What This Does NOT Cover (deferred to recall plan)

- Answer-time assembly with trust hierarchy
- Temporal operators and temporal queries
- Abstention / evidence sufficiency scoring
- Batch/skip low-value reflections (cost optimization)
- Recall limit increases / search improvements
- cold_memory full table scan performance

These are recall-side improvements and will be planned separately.

---

## What NOT to Change

- Three-tier architecture — keep day → hot → cold
- Totem/trait relational tables — keep, they serve structured lookup
- Hot memory markdown format — keep, journal is canonical narrative
- Identity/drift/drives — keep, core to product
- Salience gating — keep for DayMoment creation
