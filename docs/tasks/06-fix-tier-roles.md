# Task 06: Fix Tier Roles — Three True Tiers

## Problem

The three-tier architecture exists structurally but the roles are wrong.
Validated against shopkeeper production data (22 days, 3,227 cycles) and
longmemeval benchmark (6.8% accuracy, 83% "I don't know" responses,
246,738 totems created but unretrievable).

**Current state:**
- **Hot** is unbounded (200K tokens in 22 days), too big to dump into context,
  too unstructured to search well (keyword grep)
- **Cold** only stores embedding vectors, raw events are lost on flush,
  never searched at query time
- **Totems/traits** sit in separate SQLite tables with keyword-only search,
  forming a 5-tier system that's unnecessarily complex
- **Recall** has one path: keyword grep on hot markdown. 6.8% on longmemeval.

**Target state — three true tiers:**

| Tier | Storage | Role | Size |
|------|---------|------|------|
| **Day** | SQLite `day_memory` | Intake buffer, flushed after sleep | Transient |
| **Hot** | Markdown files, capped ~15K tokens | Always in context. Distilled identity, recent summaries, active threads. Grep is precise here because the set is small and curated. | Bounded |
| **Cold** | Unified SQLite with embeddings | Permanent archive. Raw events + totems + traits, all embedded, all semantically searchable. | Grows forever |

**Recall becomes dual-path:**
1. **Grep hot** — precise keyword hits on small, curated markdown (high precision)
2. **Semantic search cold** — embed query, cosine-match against unified cold archive (high recall)
3. **Merge + rank** — combine both, best of both worlds

Grep catches exact matches fast. Semantic search catches what grep misses
("Target" for "What store?"). Neither alone is sufficient.

---

## Phase 1: Unified Cold Archive + Semantic Recall at Query Time

**Goal:** Merge cold_embeddings, totems, and traits into one semantically
searchable archive. Make it queryable at recall time, not just during sleep.

### 1a. Unified cold table

Currently three separate tables:
- `cold_embeddings` — embedding vector + content string (no raw event data)
- `totems` — entity/context/weight/category (no embedding)
- `traits` — key/value/confidence (no embedding)

Merge into one `cold_memory` table (or unify the search interface):

```
cold_memory:
  id              TEXT PRIMARY KEY
  content         TEXT        -- readable text (reflection, "Target: Store where Alice shops", "favorite_color: blue")
  raw_content     TEXT        -- original event text (NULL for totems/traits)
  embedding       BLOB        -- OpenAI text-embedding-3-small vector
  entry_type      TEXT        -- "event", "totem", "trait"
  visitor_id      TEXT        -- NULL for global entries
  weight          REAL        -- totem weight or trait confidence (default 1.0)
  category        TEXT        -- totem category or trait category
  metadata        TEXT        -- JSON blob (event_type, salience, valence, etc.)
  source_moment_id TEXT
  created_at      TIMESTAMP
```

One table, one search path. Totem weight and trait confidence factor into
ranking: `final_score = cosine_similarity * 0.7 + weight * 0.3`.

**Migration:** Keep old tables, add new table, backfill existing data.
New writes go to `cold_memory`. Old read paths fall back to legacy tables.

**Files:** `alive_memory/storage/sqlite.py`

### 1b. Embed everything during consolidation

During full sleep, after LLM reflection:

- **Events:** embed the reflection text (already happens for top 50 — remove
  the cap, embed all). Store raw `DayMoment` content alongside.
- **Totems:** embed `f"{entity}: {context}"` at extraction time. Cost: ~10
  tokens per totem, negligible.
- **Traits:** embed `f"{category}/{key}: {value}"` at extraction time.

All go into `cold_memory` with appropriate `entry_type`.

**Files:** `alive_memory/consolidation/__init__.py`,
`alive_memory/consolidation/fact_extraction.py`

### 1c. Semantic search at query time

Add cold search to the recall pipeline. Currently `recall()` in hippocampus
never touches cold. After this change:

```python
async def recall(query, reader, state, *, embedder=None, storage=None, ...):
    ctx = RecallContext(query=query)

    # Path 1: Grep hot (precise, small set)
    hits = reader.grep_memory(query, limit=limit)
    # ... categorize into ctx as before

    # Path 2: Visitor direct lookup (unchanged)
    if visitor_id:
        await _fetch_visitor_context(visitor_id, storage, ctx)

    # Path 3: Semantic cold search (NEW)
    if embedder and storage:
        query_vec = await embedder.embed(query)
        cold_hits = await storage.search_cold_memory(query_vec, limit=10)
        for hit in cold_hits:
            # merge into appropriate ctx bucket based on entry_type
            _merge_cold_hit(hit, ctx)

    return ctx
```

Grep and semantic results are merged. Duplicates deduplicated by content hash.

**Files:** `alive_memory/recall/hippocampus.py`, `alive_memory/recall/__init__.py`,
`alive_memory/__init__.py`

### 1d. Scaling note

Current `search_cold()` is brute-force: loads all vectors, cosine-matches in
Python. This is fine for current scale:
- LongMemEval: ~500 entries per question instance
- Shopkeeper 22 days: ~16K entries
- Even at 100K entries, brute-force cosine over 1536-dim vectors takes <1s

When scale demands it, migrate to `sqlite-vec` (SQLite extension, ANN index,
no external service, keeps single-file DB philosophy). Every competing system
(Mem0, Zep, RAG baselines) uses HNSW via ChromaDB. `sqlite-vec` gives us the
same O(log N) search without adding a dependency on ChromaDB.

Not blocking. Note for future.

### 1e. Tests

- Unified cold round-trip: store event, totem, trait → search semantically →
  find all three by meaning
- Dual-path recall: grep finds keyword match in hot, semantic finds non-keyword
  match in cold, both appear in RecallContext
- Weight blending: high-weight totem ranks above low-weight totem at similar
  cosine distance
- Backward compat: legacy `cold_embeddings`/`totems`/`traits` tables still
  readable
- Visitor direct lookup still works (unchanged path)

---

## Phase 2: Bounded Hot Memory with Dynamic Categories

**Goal:** Hot memory stays small enough to dump into the LLM context window
every call (~15K tokens). Subdirectories are created organically by the LLM
during consolidation, not hardcoded. Each full sleep cycle distills hot into
tight summaries. Safe because raw events are archived in cold (Phase 1).

### 2a. LLM-driven dynamic subdirectories

Currently subdirs are hardcoded: `journal, visitors, threads, reflections,
self, collection`. The routing logic in `apply_reflection_to_hot_memory()`
is hardcoded if/else based on event metadata.

**New approach:** The LLM already reflects on each moment during consolidation.
Add one field to the reflection prompt — `categories`:

```json
{
  "reflection": "Alice complained about the broken vase...",
  "categories": ["complaints", "alice"],
  "totems": [...],
  "traits": [...]
}
```

The reflection prompt includes the list of existing subdirs so the LLM
converges on a stable set rather than creating duplicates:

```
Existing categories: journal, self, customers, complaints, inventory

Categorize this reflection. Use existing categories when they fit.
Only create a new category if none of the existing ones apply.
```

`reader.list_subdirs()` provides the current list. First sleep cycle the
LLM only sees `journal, self` → creates what it needs. By day 3, the set
stabilizes. A shopkeeper organically develops `customers/`, `inventory/`,
`complaints/`. A founder agent develops `hiring/`, `product/`, `investors/`.

**Changes:**

- `hot/writer.py` — remove hardcoded `SUBDIRS`. Replace `_ensure_dirs()`
  with `_ensure_subdir(name)` that creates on demand. Add general-purpose
  `append(subdir, filename, content)` method. **Sanitize subdir names:**
  lowercase, alphanumeric + hyphens only, strip `..` and `/`, max 30 chars.
  Reject names that don't survive sanitization.
  ```python
  def _sanitize_subdir(self, name: str) -> str:
      safe = re.sub(r"[^a-z0-9-]", "-", name.lower().strip())
      safe = re.sub(r"-+", "-", safe).strip("-")[:30]
      if not safe or safe in (".", ".."):
          raise ValueError(f"Invalid category name: {name!r}")
      return safe
  ```
- `hot/reader.py` — add `list_subdirs() -> list[str]` that returns all
  existing subdirs dynamically via `os.listdir`. Update `grep_memory` to
  use `list_subdirs()` instead of hardcoded list.
- `consolidation/reflection.py` — add `categories` to the reflection
  prompt output schema. Include existing subdirs in prompt context.
- `consolidation/memory_updates.py` — replace hardcoded routing with
  LLM-returned categories. For each category, call
  `writer.append(subdir=category, filename, content)`.
- `recall/hippocampus.py` — update grep hit routing to handle dynamic
  categories. Instead of fixed if/else mapping subdirs to `RecallContext`
  fields, use a catch-all bucket for non-standard subdirs:
  ```python
  # Known subdirs → existing RecallContext fields
  _SUBDIR_MAP = {
      "journal": "journal_entries",
      "visitors": "visitor_notes",
      "self": "self_knowledge",
      "reflections": "reflections",
      "threads": "thread_context",
  }
  # Dynamic subdirs → generic bucket
  field = _SUBDIR_MAP.get(subdir, "extra_context")
  ```
- `types.py` — add `extra_context: list[str]` field to `RecallContext`
  for hits from dynamic categories. Include in `to_prompt()` output.
- Config: optional `hot.pinned_subdirs = ["journal", "self"]` — always
  created at init. Optional `hot.max_subdirs = 20` — safety cap.

**Files:** `alive_memory/hot/writer.py`, `alive_memory/hot/reader.py`,
`alive_memory/consolidation/reflection.py`,
`alive_memory/consolidation/memory_updates.py`,
`alive_memory/recall/hippocampus.py`, `alive_memory/types.py`,
`alive_memory/config.py`

### 2b. Distillation during full sleep

Currently `apply_reflection_to_hot_memory()` only appends. Files grow
forever.

**Changes:**

- `hot/writer.py` — add `rewrite_file(subdir, filename, content)` method
  (overwrites entire file, like `write_self_file` but for any subdir)
- `consolidation/__init__.py` — after per-moment processing in full sleep,
  add a **distillation phase**:
  1. For each subdir, read all files
  2. LLM call: "Distill these entries into a concise summary.
     Preserve key facts, entities, and emotional texture. Drop redundancy."
  3. `writer.rewrite_file(subdir, filename, distilled_content)`
- Config: `consolidation.distill_hot = true` (default true)

**Files:** `alive_memory/hot/writer.py`, `alive_memory/consolidation/__init__.py`,
`alive_memory/config.py`

### 2c. Prune old hot files

- `hot/writer.py` — add `prune_old_files(subdir, max_age_days)` method
- `consolidation/__init__.py` — at end of full sleep, prune files older
  than `hot_max_days` (default 7). Safe because everything is in cold.
- Config: `consolidation.hot_max_days = 7`

**Files:** `alive_memory/hot/writer.py`, `alive_memory/consolidation/__init__.py`,
`alive_memory/config.py`

### 2d. Hot token budget

Add `hot.max_tokens` config (default 15,000). During distillation, if total
hot memory exceeds budget, aggressively summarize or prune oldest files
first. The app can tune this based on their model's context window.

**Files:** `alive_memory/config.py`, `alive_memory/consolidation/__init__.py`

### 2e. Tests

- Dynamic subdir creation: LLM returns new category → subdir created
- Subdir convergence: LLM sees existing subdirs → reuses them
- Pinned subdirs: `journal` and `self` always exist even if empty
- Max subdirs cap: 21st subdir rejected, falls back to closest existing
- Full sleep distills: verify files are shorter after sleep
- Prune removes old files: create dated files → prune → verify removal
- Distilled content preserves key facts (check substring presence)
- Token budget enforced: hot memory stays under configured limit
- Config toggle: `distill_hot=false` skips distillation
- Grep still works on distilled hot with dynamic subdirs

---

## Phase 3: Identity-Aware Salience

**Goal:** Salience scoring reflects what matters to *this* agent.

### 3a. Accept salience from host framework

The host app already calls an LLM every cycle. Let it pass
`metadata={"salience": 0.8}` and skip the heuristic entirely. This path
already exists in `thalamus.py` but isn't documented.

**Changes:**

- `docs/INTEGRATIONS.md` — document the `metadata.salience` override
- `intake/thalamus.py` — when `metadata.salience` is provided, skip
  heuristic computation (currently computes then overrides — wasteful)

**Files:** `alive_memory/intake/thalamus.py`, `docs/INTEGRATIONS.md`

### 3b. Identity-based salience boost (optional)

If the agent has a self-model with identity traits, boost salience for
events matching identity-relevant categories.

**Changes:**

- `intake/thalamus.py` — add optional `identity_keywords: list[str]` param.
  If any keyword appears in content, boost by `config.intake.identity_boost`
  (default 0.15)
- `alive_memory/__init__.py` — on `intake()`, extract identity keywords
  from self-model and pass to `perceive()`

**Files:** `alive_memory/intake/thalamus.py`, `alive_memory/__init__.py`

### 3c. Remove artificial day memory cap

`MAX_DAY_MOMENTS = 30` is too restrictive. Consolidation costs ~$0.005/day.

- Raise to 500 (safety valve, not a real limit)
- Keep lowest-salience eviction as emergency overflow only

**Files:** `alive_memory/intake/formation.py` or wherever the cap is enforced

### 3d. Tests

- Identity boost: shopkeeper identity → customer event scores higher than
  weather event
- Metadata override: `metadata={"salience": 0.9}` bypasses heuristic
- No cap: >30 moments recorded without eviction

---

## Implementation Order

```
Phase 1 (unified cold + semantic recall)    ← biggest accuracy impact
  1a: unified cold_memory table + migration
  1b: embed events, totems, traits during consolidation
  1c: dual-path recall (grep hot + semantic cold)
  1d: (future) sqlite-vec for scaling
  1e: tests

Phase 2 (bounded hot + dynamic categories)   ← fixes unbounded growth
  2a: LLM-driven dynamic subdirectories
  2b: distillation during full sleep
  2c: prune old hot files
  2d: hot token budget
  2e: tests

Phase 3 (identity-aware salience)           ← quality of life
  3a: document metadata.salience override
  3b: identity boost
  3c: remove cap
  3d: tests
```

Phase 1 must land first — Phase 2 (pruning hot) depends on cold having the
raw archive so nothing is lost.

## Embedding Provider

All semantic features use OpenAI `text-embedding-3-small` (1536 dims) via
`OpenAIEmbeddingProvider` in `alive_memory/embeddings/api.py`. The local
hash-based embedder is a fallback for tests but produces random recall quality.

## Cost Estimate (shopkeeper scale)

| Operation | Volume/day | Cost/day |
|-----------|-----------|----------|
| Embed events to cold | ~50 moments × ~50 tokens | $0.0001 |
| Embed totems + traits | ~30 new × ~15 tokens | $0.00001 |
| Embed recall queries | ~100 queries × ~20 tokens | $0.00004 |
| Distill hot memory (LLM) | 1 call × ~2K tokens | $0.003 |
| **Total new cost** | | **~$0.004/day** |

## Files Changed (all phases)

```
alive_memory/storage/sqlite.py              # unified cold_memory table, semantic search, migration
alive_memory/consolidation/__init__.py      # embed all to cold, distillation phase
alive_memory/consolidation/fact_extraction.py  # embed totems + traits at creation
alive_memory/consolidation/reflection.py    # add categories to reflection prompt
alive_memory/consolidation/memory_updates.py  # LLM-driven subdir routing
alive_memory/recall/hippocampus.py          # dual-path: grep hot + semantic cold
alive_memory/recall/__init__.py             # embedder param
alive_memory/hot/writer.py                  # dynamic subdirs, rewrite_file, prune
alive_memory/hot/reader.py                  # list_subdirs(), dynamic grep
alive_memory/intake/thalamus.py             # identity boost, skip heuristic on override
alive_memory/__init__.py                    # wire embedder to recall, identity keywords
alive_memory/config.py                      # hot.pinned_subdirs, hot.max_subdirs, hot.max_tokens, distill_hot, hot_max_days
docs/INTEGRATIONS.md                        # document metadata.salience
tests/test_unified_cold.py                 # NEW — cold archive + semantic search
tests/test_dual_recall.py                  # NEW — grep + semantic combined
tests/test_hot_distillation.py             # NEW — bounded hot + dynamic subdirs
tests/test_identity_salience.py            # NEW — salience improvements
```
