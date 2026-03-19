# 08 — Recall Improvement Plan

**Date**: 2026-03-19
**Branch**: `feat/recall-raw-turn-evidence`
**Goal**: Raise LongMemEval from 37.4% toward 80%+ by fixing recall retrieval and assembly

---

## Context

PR #22 (consolidation improvement) fixed storage waste and strengthened provenance.
The storage layer now preserves raw `moment.content` in `cold_memory` with indexed
`session_id`, `turn_index`, and `role` columns.

**Key insight**: With benchmark config `salience_threshold=0.0`, all raw content already
survives in cold_memory. The 37.4% score was achieved with raw content preserved.
**The bottleneck is retrieval and assembly, not storage loss.**

However, in production mode (non-zero salience threshold), low-salience turns are
still dropped before they become durable evidence. Phase 1 fixes this for production
AND creates a distinct `RAW_TURN` entry type that recall can trust differently.

---

## Design Principle

> "recall decides ordering, answer_query decides packing."

- **recall()** = retrieval + ranking + evidence assembly (trust-ordered)
- **answer_query()** = budget-aware context construction (token-limited)

---

## Implementation Order

### Phase 1: Canonical Raw-Turn Storage at Intake

**Goal**: Every conversation turn becomes durable evidence, even if it never becomes a DayMoment.

**Changes**:

1. `alive_memory/types.py`
   - Add `ColdEntryType.RAW_TURN = "raw_turn"`

2. `alive_memory/__init__.py` → `intake()`
   - Before `form_moment()`, if event_type is conversation-like:
     - Write raw turn immediately to `cold_memory` with `entry_type=RAW_TURN`
     - Include: raw_content, content, session_id, turn_index, role, timestamp, metadata
     - If embedder exists, embed immediately
     - If no embedder, store without embedding (backfill later)

3. `alive_memory/storage/base.py` and `alive_memory/storage/sqlite.py`
   - Support `raw_turn` as first-class entry_type
   - Add retrieval helpers:
     - `get_turns_by_session(session_id, start_turn?, end_turn?)` — fetch turn window
     - `get_neighboring_turns(session_id, turn_index, window=3)` — expand around a hit

**Tests**:
- Non-salient exact fact survives: low-salience turn never becomes DayMoment but recall finds it
- Neighbor expansion: matched turn returns surrounding context from same session

---

### Phase 2: Trust-Ordered Recall Assembly

**Goal**: Recall produces evidence in trust order, not merged buckets.

**New assembly order**:
1. Raw turn evidence (exact quoted turns + neighbors around hits)
2. Structured facts (visitor profile, traits, totems)
3. Active thread / recent hot context
4. Reflections / summaries
5. Extra context

**Changes**:

1. `alive_memory/recall/hippocampus.py`
   - Split retrieval into stages
   - Raw turn search first (search cold_memory with entry_type=RAW_TURN)
   - Group by session, expand local window around hits
   - Dedupe semantically redundant evidence
   - Suppress weaker abstract summaries if raw evidence exists

2. `alive_memory/types.py` → extend `RecallContext`
   - Add fields:
     - `raw_turns: list[str]`
     - `evidence_blocks: list[EvidenceBlock]` (text, source_type, trust_rank, timestamp, session_id, score)
     - `confidence: float`
     - `abstain_recommended: bool`
   - Keep current property aliases for backwards compat

**Tests**:
- Raw evidence outranks reflections when both match
- Duplicate evidence is suppressed

---

### Phase 3: Token-Budget Packing in Benchmark Adapter

**Goal**: Replace hardcoded per-bucket caps with budget-aware packing.

**Current problem** in `benchmarks/academic/systems/alive_system.py`:
```python
# Dumb fixed slicing — throws away evidence
journal_entries[:5]
visitor_notes[:3]
self_knowledge[:3]
reflections[:3]
totem_facts[:10]
trait_facts[:10]
cold_echoes[:3]
```

**Changes**:

1. `benchmarks/academic/systems/alive_system.py` → `answer_query()`
   - Replace manual `context_parts` slicing
   - Add `_build_ordered_evidence(ctx)` — extract evidence blocks in trust order
   - Add `_pack_context_to_budget(evidence_blocks, token_budget=12000)` — fill budget

2. Packing behavior:
   - Estimate tokens cheaply (chars / 4)
   - Include section headers
   - Favor trust order first, diversity second
   - Avoid duplicates / near-duplicates
   - Keep chronological locality for raw-turn clusters

**Tests**:
- Packing by budget, not bucket caps
- Direct raw evidence survives even when many journal/reflection items exist
- Higher-trust evidence included before lower-trust
- Latest contradictory fact packed before stale fact

---

### Phase 4: Recency / Contradiction Handling

**Goal**: Latest fact wins when evidence contradicts.

**Example**: "I live in Osaka" → later "I moved to Kyoto" → recall surfaces Kyoto first.

**Changes**:
- Session/time-aware ranking in recall
- Prefer: more recent raw evidence, explicit corrections, traits with newer provenance
- Surface as: current_fact + prior_fact (not equal weight)

**Files**: `alive_memory/recall/hippocampus.py`, possibly new `alive_memory/recall/evidence.py`

---

### Phase 5: Temporal Operators

**Goal**: Support temporal queries (before/after/when/first/latest/last week).

**Changes**:
- Parse temporal hints from query
- Filter or rerank candidates by timestamp/session chronology
- Format returned evidence with relative time labels

**Files**: `alive_memory/recall/hippocampus.py`, new `alive_memory/recall/temporal.py`

---

### Phase 6: Abstention / Confidence

**Goal**: Signal when evidence is insufficient.

**Low confidence when**:
- No raw-turn hits
- Low semantic similarity
- Only vague reflections matched
- Poor lexical overlap
- Conflicting evidence with no recent winner

**Output**: `confidence = low`, `abstain_recommended = True`

---

## Files Touched

| File | Phase |
|------|-------|
| `alive_memory/types.py` | 1, 2 |
| `alive_memory/__init__.py` | 1 |
| `alive_memory/storage/base.py` | 1 |
| `alive_memory/storage/sqlite.py` | 1 |
| `alive_memory/recall/hippocampus.py` | 2, 4, 5 |
| `benchmarks/academic/systems/alive_system.py` | 3 |
| `alive_memory/recall/evidence.py` (new) | 4 |
| `alive_memory/recall/temporal.py` (new) | 5 |
| `tests/test_unified_cold.py` | 1 |
| `tests/test_recall_evidence.py` (new) | 2, 3, 4, 5, 6 |

## What NOT to Change

- Three-tier architecture (day → hot → cold)
- Totem/trait relational tables
- Hot memory markdown format
- Identity/drift/drives
- Salience gating for DayMoment creation (raw turns bypass it, not replace it)
- Consolidation pipeline (PR #22 just landed, leave it stable)
