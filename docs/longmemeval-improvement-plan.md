# LongMemEval Improvement Plan

**Goal**: Raise alive-memory from 37.4% to 80%+ accuracy on LongMemEval
**Date**: 2026-03-19

## Root Cause Analysis

Mastra OM scores 95% by doing something radically simple: **no retrieval**. They compress all conversations into ~30k tokens of observation notes and inject them into the context window every turn. The LLM sees everything and reasons over it directly.

alive-memory's three-tier pipeline (day → hot → cold) loses information at every stage:
1. Salience gating drops events
2. Reflection abstracts away exact details (names, numbers, dates)
3. Keyword grep misses semantically related memories
4. Vector search top-k cutoff drops relevant results
5. Assembled recall context is a curated subset, not the full picture

**The fundamental issue**: alive-memory was designed for persistent AI characters, not factual recall benchmarks. The cognitive richness (dreaming, drives, identity) is irrelevant to LongMemEval. But the architecture CAN be adapted.

## What Mastra Does (and we don't)

| Feature | Mastra OM | alive-memory |
|---|---|---|
| Raw fact preservation | YES — Observer keeps exact facts with priority tags | NO — reflection abstracts away details |
| Full context injection | YES — all observations in every prompt | NO — selective grep/vector retrieval |
| Temporal awareness | YES — three-date model (obs date, ref date, relative) | NO — timestamps stored but not surfaced |
| Compression | YES — Observer (3-6x) + Reflector (multi-level) | YES — but lossy consolidation |
| Retrieval | NONE — everything in context | Keyword grep + vector search |
| Abstention | Implicit — LLM calibrated by seeing all context | NONE — always generates an answer |

## Proposed Changes (Priority Order)

### Phase 1: Raw Turn Storage (Highest Impact)

**Problem**: Consolidated reflections lose exact details LongMemEval tests for.

**Solution**: Store raw conversation turns in cold tier alongside reflections. During recall, search raw turns directly.

- Add `cold_turns` table: `(id, session_id, turn_id, role, content, timestamp, embedding)`
- On intake, store the raw turn content (in addition to creating a moment)
- On recall, search `cold_turns` by vector similarity and return raw text
- Recall assembles: raw turn hits + existing hot memory + cold reflections

**Effort**: Medium
**Expected impact**: +15-20% accuracy (information extraction and knowledge updates)

### Phase 2: Context Assembly Overhaul

**Problem**: Recall returns a curated subset. If retrieval misses, the answer is wrong.

**Solution**: Build a comprehensive context block (like Mastra's observations) instead of selective retrieval.

Option A — **Observation layer** (Mastra-style):
- Add an Observer step that runs during intake, producing compressed observation notes
- Store observations as a running text blob
- On recall, inject full observation blob into context
- Add Reflector to compress when observations exceed token threshold

Option B — **Hybrid recall** (less invasive):
- Keep existing three-tier architecture
- On recall, assemble ALL available context up to a token budget (~30k):
  1. All totem facts and traits (structured, small)
  2. All journal entries (chronological)
  3. Top-k cold embeddings (fill remaining budget)
  4. Raw turn hits from Phase 1
- Let the LLM reason over the full assembled context

**Recommendation**: Start with Option B (less disruptive), measure. If insufficient, add Option A.

**Effort**: Medium-High
**Expected impact**: +10-15% accuracy (multi-session reasoning)

### Phase 3: Temporal Indexing

**Problem**: 15.7% on temporal reasoning. No mechanism to answer "before/after/when" questions.

**Solution**:
- Index moments and raw turns by timestamp
- Support temporal queries in recall: `recall(query, temporal_hint="before 2024-03-15")`
- During context assembly, add relative time markers: "3 months ago", "last week"
- Add date-aware observation formatting (like Mastra's `addRelativeTimeToObservations`)

**Effort**: Medium
**Expected impact**: +15-20% on temporal reasoning category

### Phase 4: Abstention Logic

**Problem**: 3.3% on abstention. alive-memory never says "I don't know."

**Solution**:
- After recall, compute a confidence score based on:
  - Relevance of top results (cosine similarity)
  - Coverage (how many recall sources returned results)
  - Keyword overlap between query and recalled context
- If confidence < threshold, prepend "Based on our conversations, I don't have information about this" to the context
- Alternative: Add explicit instruction in answer generation prompt: "If the conversation history does not contain the answer, say 'I don't know'"

**Effort**: Low
**Expected impact**: +5-10% on abstention, slight improvement on other categories (fewer hallucinated answers)

### Phase 5: Selective Reflection (Cost Reduction)

**Problem**: Reflecting on every moment costs ~$85 per benchmark run.

**Solution**:
- Only reflect on moments with salience > threshold (e.g., 0.3)
- Skip greetings, acknowledgments, filler turns
- Batch multiple low-salience moments into a single reflection call
- Use salience to determine reflection depth (high salience = detailed, low = brief)

**Effort**: Low
**Expected impact**: 3-5x cost reduction, minimal accuracy impact (low-salience moments contribute little to recall)

## Product Gaps for Always-On Human-Like Agents

LongMemEval measures factual recall, but the product goal is broader:
always-on agents with stable identity and stable tastes. The target class is
**autobiographical, identity-preserving, emotionally weighted memory for
persistent agents**. The same work that improves benchmarks must also protect
those product properties.

LongMemEval should be treated as a factual recall and temporal reasoning
track, not as the deciding proof for the product. A change that raises
LongMemEval but weakens self-continuity, visitor taste currentness,
emotionally weighted recall, or person boundaries is not a win for
alive-memory.

### Gap 1: Durable Hot Memory Defaults

If `memory_dir` is omitted, hot memory lives in a temporary directory. That is
acceptable for tests, but unsafe for an always-on agent because journal,
reflection, visitor, and self-knowledge files can disappear after restart.

**Fix**: derive a durable default `memory_dir` beside the SQLite DB, or make
the constructor warn loudly when `memory_dir` is omitted outside tests.

### Gap 2: First-Class Identity Metadata

Preference and trait extraction depend on `visitor_id` or `visitor_name`.
Plain `intake()` does not require stable person/session metadata, so callers
can accidentally create memories that cannot become structured tastes.

**Fix**: add first-class metadata support for `agent_id`, `visitor_id`,
`session_id`, `turn_index`, `role`, and timestamp. Treat missing
`visitor_id` as an integration warning for conversation memory.

### Gap 3: Current Preferences, Not Append-Only Preferences

Contradictions are detected but not resolved into a current-state preference
model. If a visitor says "I like coffee" and later "I hate coffee", both
observations can remain live.

**Fix**: add supersession state to traits and totems: `active`,
`superseded_by`, `valid_from`, `valid_until`, and `evidence_count`. Recall
should prefer active current facts and surface conflict only when useful.

### Gap 4: Self-Model Is Not Yet Automatic

The self-model API supports trait updates and narrative regeneration, but
normal sleep does not yet derive stable agent identity, style, or tastes from
observed behavior.

**Fix**: add a self-model consolidation pass after daily summary. It should
derive candidate self traits from actions, reflections, and corrections, then
update the self-model through guard rails and drift checks.

### Gap 5: Scoped Recall and Person Boundaries

Recall can do direct visitor lookup, but it also runs global totem and trait
search. In multi-person settings, this can leak one person's preferences into
another person's context.

**Fix**: make scoped recall the default when a `visitor_id` is known. Global
facts should be opt-in, separately ranked, and labeled.

## Proof Plan

To prove alive-memory is better than other frameworks, run public benchmarks
and product-specific evals under identical budgets. The comparison should
include no-memory, full-context, raw-turn vector RAG, summary memory, Mem0,
Zep, and alive-memory.

### SOTA Competitor Set

Do not compare only against simple baselines. The proof set must include
systems that represent different current SOTA strategies:

| System | Strategy | Why It Matters |
|--------|----------|----------------|
| Mastra Observational Memory | Background Observer/Reflector maintains stable observation context | Strong LongMemEval results and a direct challenge to selective retrieval |
| EmergenceMem-style RAG | Optimized retrieval over processed conversation history | Shows how far careful RAG can go before adding cognitive machinery |
| Mem0 | Structured fact/profile extraction with low token and latency overhead | Common production memory baseline for personalization |
| Zep/Graphiti | Temporal knowledge graph with hybrid semantic, keyword, and graph search | Strong on changing facts, relationship memory, and temporal currentness |
| Hindsight | Structured memory plus semantic/BM25/graph/temporal/rerank retrieval | Important for BEAM-style scale where context stuffing is impossible |
| MemMachine | Ground-truth-preserving episodic/profile memory with contextual retrieval | Directly attacks lossy extraction by keeping full conversational episodes |
| Letta/MemGPT | Agent-managed working + archival memory via tool use | Tests whether self-editing memory beats external background maintenance |
| LangMem/LangGraph memory | Semantic, episodic, and procedural memory in a common agent stack | Practical baseline for teams already using LangGraph |
| Full-context/oracle | Put all or known-relevant conversations in context | Establishes the upper bound and detects benchmark weaknesses |

Each competitor must run under matched answer model, ingestion model, embedding
model, token budget, latency budget, and storage accounting. If a vendor
reports a result with stronger actor models or hidden preprocessing, record it
as a reference number, not a direct win/loss comparison.

Required proof:

- alive-memory beats baselines on identity consistency and taste consistency
- alive-memory beats baselines on autobiographical continuity: grounded self
  narrative, current visitor model, affective salience, and change legibility
- alive-memory is competitive on factual recall and cross-session recall
- alive-memory has lower entity/person confusion than generic RAG
- alive-memory handles preference corrections better than append-only memory
- alive-memory reports uncertainty instead of hallucinating when recall is weak
- gains hold on held-out and production regression cases, not just train cases
- latency, storage, and LLM cost remain inside product budgets

## Expected Outcome

| Phase | Category Impact | Estimated New Accuracy |
|---|---|---|
| Baseline | — | 37.4% |
| Phase 1 (raw turns) | Info extraction, knowledge updates | ~55% |
| Phase 2 (context overhaul) | Multi-session | ~65% |
| Phase 3 (temporal) | Temporal reasoning | ~75% |
| Phase 4 (abstention) | Abstention | ~78% |
| Phase 5 (cost) | No accuracy change | ~78% (at 1/4 cost) |

## What NOT to Change

- **Three-tier architecture** — Keep it. It serves the character persistence use case. Just add raw turn storage alongside it.
- **Totem/trait extraction** — Keep it. Structured facts are useful for character identity, even if they're not the primary recall mechanism for benchmarks.
- **Hot memory markdown** — Keep it. Journal/visitor notes serve the character narrative. Just don't rely on them as the primary recall source.
- **Identity/drift/drives** — Keep it. Not relevant to benchmarks but core to the product.

## Measurement Plan

After each phase, re-run LongMemEval with 16 workers:
```bash
OPENAI_API_KEY='...' nohup .venv/bin/python -u -m benchmarks.academic.parallel_run \
    --benchmark longmemeval --system alive --workers 16 > benchmark_output.log 2>&1 &
```

Compare per-category accuracy against this baseline and against Mastra OM (94.9%).
