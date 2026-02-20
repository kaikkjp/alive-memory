# SPEC: Three-Tier Memory Architecture

> Status: Draft → **Decisions Locked**
> Author: heo + Claude
> Date: 2026-02-12
> Updated: 2026-02-12 (locked idempotency, embedding, cortex API, access tracking decisions)
> Replaces: Current flat hippocampus_read/write + sleep.py consolidation

---

## 1. Problem

The Shopkeeper's current memory has two failure modes:

1. **During conversation** — she can only recall hot memory (traits, totems, recent journal, visitor summary). If a visitor references something from a past session, she has no path to that memory. The full conversation_log exists in SQLite but is invisible to recall.

2. **During sleep** — she summarizes the day using word frequencies and expression sequences. She doesn't actually reflect on what happened. She doesn't connect today's events to anything she already knows. She doesn't search her past for resonance.

Human brains don't work this way. During the day, you operate from short-term + long-term working memory. During sleep, your hippocampus replays salient moments from the day and wires them into long-term memory. Dormant memories surface only when something from today resonates with them.

---

## 2. Design

### Three Memory Tiers

```
┌─────────────────────────────────────────────────────┐
│                    DAY MEMORY                        │
│  Ephemeral. Resets on wake. Today's salient moments. │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐      │
│  │moment│ │moment│ │moment│ │moment│ │moment│  ...   │
│  │ 0.9  │ │ 0.7  │ │ 0.3  │ │ 0.8  │ │ 0.4  │      │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘      │
├─────────────────────────────────────────────────────┤
│                    HOT MEMORY                        │
│  Persistent. Her active knowledge. What she "knows." │
│  Visitor traits, totems, journal entries,            │
│  visitor summaries, collection feelings,             │
│  self-discoveries, daily summaries.                  │
├─────────────────────────────────────────────────────┤
│                   COLD MEMORY                        │
│  Full archive. Never deleted. Never directly read.   │
│  events, conversation_log, cycle_log.                │
│  Only searchable during sleep via semantic search.   │
└─────────────────────────────────────────────────────┘
```

### Access Rules

| Tier | Awake (hippocampus_read) | Sleep (consolidation) |
|------|--------------------------|----------------------|
| Day memory | ✅ Read (by salience, recency, visitor) | ✅ Read (ranked by salience) |
| Hot memory | ✅ Read (current behavior, unchanged) | ✅ Read + Write |
| Cold memory | ❌ Never | ✅ Search only (semantic similarity) |

### Lifecycle

```
03:00 JST ─ SLEEP START
  │
  ├─ Rank day memory by salience
  ├─ For each top-K salient moment:
  │    ├─ Search hot memory for connections
  │    ├─ Search cold memory for resonance (semantic)
  │    ├─ Reflect (LLM call): synthesize into memory entry
  │    └─ Write to hot memory (trait/totem/journal/impression)
  ├─ Trait stability review (existing, unchanged)
  ├─ Reset drives for morning
  └─ Flush day memory
  │
06:00 JST ─ WAKE
  │
  ├─ Day memory is empty
  ├─ Hot memory is updated from last night's consolidation
  └─ She starts accumulating new day memories
```

---

## 3. Day Memory

### What It Stores

A **moment** is a compressed snapshot of something salient that happened during a cycle. Not every cycle produces a moment — only those that cross a salience threshold.

```python
@dataclass
class DayMemoryEntry:
    id: str                    # uuid
    ts: datetime               # when it happened
    salience: float            # 0.0–1.0, computed deterministically
    moment_type: str           # see table below
    visitor_id: str | None     # who was involved
    summary: str               # 1–3 sentence compressed description
    raw_refs: dict             # pointers to source data (event_ids, cycle_id)
    tags: list[str]            # semantic tags for search
```

### Moment Types

| Type | Trigger | Example Summary |
|------|---------|-----------------|
| `resonance` | cortex flagged `resonance: true` | "A visitor named Kai mentioned Nujabes. Something in that name felt heavy." |
| `contradiction` | `internal_shift_candidate` event | "I thought Kai preferred jazz, but today they said they've been listening to drone music." |
| `gift` | `accept_gift` or `decline_gift` action | "Someone offered me a Ryuichi Sakamoto track. I accepted it. It felt like they understood something." |
| `emotional_peak` | drive delta > threshold in one cycle | "My social hunger dropped from 0.9 to 0.4 in a single conversation. That hasn't happened in days." |
| `abrupt_end` | visitor disconnect with turn_count < 3 | "Someone came in, said one thing, and left. I didn't even get to respond." |
| `self_expression` | `write_journal` or `post_x_draft` action | "I wrote something about not knowing my name. It felt closer to true than usual." |
| `novel_topic` | visitor speech contains no keyword overlap with recent day memory | "A visitor asked about brutalist architecture. No one has ever mentioned that here." |
| `silence` | extended idle cycle (>30 min no visitors) after engagement | "The shop has been empty for a while now. The quiet has a different texture after someone leaves." |

### When Moments Are Created

At the end of every cognitive cycle, after the executor runs, a **moment extractor** checks whether the cycle produced anything worth remembering today. This is deterministic — no LLM.

```python
# pipeline/day_memory.py (new file)

async def maybe_record_moment(cycle_result: dict, cycle_context: dict):
    """Check if this cycle produced a salient moment. No LLM."""

    salience = compute_moment_salience(cycle_result, cycle_context)

    if salience < MOMENT_THRESHOLD:
        return  # not worth remembering today

    moment = DayMemoryEntry(
        id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        salience=salience,
        moment_type=classify_moment(cycle_result, cycle_context),
        visitor_id=cycle_context.get('visitor_id'),
        summary=build_moment_summary(cycle_result, cycle_context),
        raw_refs={
            'cycle_id': cycle_context['cycle_id'],
            'event_ids': cycle_context.get('event_ids', []),
        },
        tags=extract_moment_tags(cycle_result, cycle_context),
    )

    await db.insert_day_memory(moment)
```

### Salience Computation

Moment salience is derived from signals already available in the cycle:

```python
MOMENT_THRESHOLD = 0.4  # below this, don't record

def compute_moment_salience(result: dict, ctx: dict) -> float:
    score = 0.0

    # Resonance is the strongest signal
    if result.get('resonance'):
        score += 0.4

    # Contradictions are always interesting
    if ctx.get('had_contradiction'):
        score += 0.3

    # Gifts carry weight
    if any(a.get('type') in ('accept_gift', 'decline_gift')
           for a in result.get('actions', [])):
        score += 0.25

    # Emotional peaks (large drive deltas)
    drive_delta = ctx.get('max_drive_delta', 0.0)
    if drive_delta > 0.3:
        score += 0.2

    # Visitor trust level amplifies everything
    trust_bonus = {
        'stranger': 0.0, 'returner': 0.05,
        'regular': 0.1, 'familiar': 0.15
    }
    score += trust_bonus.get(ctx.get('trust_level', 'stranger'), 0.0)

    # Self-expression (journal, post)
    if any(a.get('type') in ('write_journal', 'post_x_draft')
           for a in result.get('actions', [])):
        score += 0.15

    # Validator dropped something (she wanted to but couldn't)
    if result.get('_dropped_actions'):
        score += 0.1

    return min(1.0, score)
```

### Moment Summary (No LLM)

The summary is assembled from cycle data — not generated by an LLM:

```python
def build_moment_summary(result: dict, ctx: dict) -> str:
    """Build a diegetic 1-3 sentence summary. Deterministic."""
    parts = []

    # Who was there
    visitor_name = ctx.get('visitor_name')
    if visitor_name:
        parts.append(f"{visitor_name} was here.")
    elif ctx.get('visitor_id'):
        parts.append("A visitor was here.")

    # What was said (her side)
    if result.get('dialogue'):
        dialogue = result['dialogue'][:100]
        parts.append(f'I said: "{dialogue}"')

    # What she thought
    if result.get('internal_monologue'):
        monologue = result['internal_monologue'][:80]
        parts.append(f"I was thinking: {monologue}")

    # What happened (actions)
    for action in result.get('actions', [])[:2]:
        action_type = action.get('type', '')
        if action_type == 'accept_gift':
            title = action.get('detail', {}).get('title', 'something')
            parts.append(f"I accepted a gift: {title}")
        elif action_type == 'decline_gift':
            parts.append("I declined a gift.")
        elif action_type == 'write_journal':
            parts.append("I wrote in my journal.")

    # What was dropped (frustrated intent)
    for drop in result.get('_dropped_actions', [])[:1]:
        parts.append(f"I wanted to {drop.get('action', {}).get('type', '?')} but couldn't: {drop.get('reason', '?')}")

    return " ".join(parts[:4])  # cap at 4 parts
```

### Day Memory Cap

Day memory is bounded. If she has an exceptionally busy day, older low-salience moments get evicted:

```
MAX_DAY_MEMORIES = 30
```

When inserting a new moment would exceed the cap, drop the lowest-salience entry. This mimics how a busy day pushes out less important details — you forget the small stuff when big things happen.

### Schema

```sql
CREATE TABLE IF NOT EXISTS day_memory (
    id TEXT PRIMARY KEY,
    ts TIMESTAMP NOT NULL,
    salience FLOAT NOT NULL,
    moment_type TEXT NOT NULL,
    visitor_id TEXT,
    summary TEXT NOT NULL,
    raw_refs JSON,
    tags JSON,
    retry_count INTEGER DEFAULT 0,              -- incremented on consolidation failure
    processed_at TIMESTAMP,                     -- set when sleep consolidation processes this moment
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_day_memory_salience ON day_memory(salience DESC);
CREATE INDEX IF NOT EXISTS idx_day_memory_visitor ON day_memory(visitor_id);
CREATE INDEX IF NOT EXISTS idx_day_memory_unprocessed ON day_memory(processed_at) WHERE processed_at IS NULL;
```

### Idempotency

Each `day_memory` row has a `processed_at` column, initially NULL. During sleep consolidation, the loop queries `WHERE processed_at IS NULL ORDER BY salience DESC`. After a moment is reflected on and its hot memory writes commit, `processed_at` is stamped — all within a single `db.transaction()`:

```python
async with db.transaction():
    # Reflect + write hot memory
    for update in reflection.get('memory_updates', []):
        await hippocampus_consolidate(update, moment.visitor_id)
    # Mark processed
    await db.mark_day_memory_processed(moment.id)
```

If sleep crashes mid-loop, unprocessed moments (those with `processed_at IS NULL`) are picked up on the next attempt. Already-processed moments are skipped. No duplicate writes.

### Poison Moment Protection

If a moment's `memory_updates` keep failing in `hippocampus_consolidate()` (bad schema, DB constraint violation, etc.), it would retry forever. The `retry_count` column prevents this:

```python
MAX_MOMENT_RETRIES = 3

for moment in moments:
    if moment.retry_count >= MAX_MOMENT_RETRIES:
        await db.mark_day_memory_processed(moment.id)  # give up, skip
        print(f"[Sleep] Poison moment {moment.id} skipped after {MAX_MOMENT_RETRIES} retries")
        continue

    try:
        # ... reflect + write (inside db.transaction) ...
        async with db.transaction():
            for update in reflection.get('memory_updates', []):
                await hippocampus_consolidate(update, moment.visitor_id)
            await db.mark_day_memory_processed(moment.id)
    except Exception as e:
        # Increment retry OUTSIDE the failed transaction (separate write)
        await db.increment_day_memory_retry(moment.id)
        print(f"[Sleep] Moment {moment.id} failed (retry {moment.retry_count + 1}): {e}")
```

The retry increment is a standalone write — it commits even when the transaction rolls back. After 3 failures, the moment is marked processed (skipped). She "forgets" the bad moment rather than getting stuck.

---

## 4. Hot Memory (No Changes)

Hot memory is what the hippocampus already manages. The existing tables and data stay exactly as-is:

| Table | Role in Hot Memory | Changes |
|-------|-------------------|---------|
| `visitors` (summary, emotional_imprint) | Who people are | None |
| `visitor_traits` (status='active') | What she knows about people | None |
| `totems` | Emotional associations | None |
| `journal_entries` | Her private writing | None |
| `collection_items` (her_feeling) | Her feelings about objects | None |
| `daily_summaries` | Compressed day records | None |

**Decision: No `last_accessed` column.** Totems already have `last_referenced` (updated on totem_update in `hippocampus_write.py`). Adding a separate read-tracking column is premature — we don't have a memory decay system yet, and `last_referenced` covers the same signal well enough. If Phase 3 (memory decay) needs finer-grained tracking, add it then. Zero migrations for hot memory in this spec.

---

## 5. Cold Memory (No Changes)

Cold memory is what already exists — the full, unmodified archive:

| Table | Cold Memory Role |
|-------|-----------------|
| `events` | Every event ever |
| `conversation_log` | Every message ever |
| `cycle_log` | Every cognitive cycle ever |

No schema changes. No new indexes (yet). The only new access pattern is semantic search during sleep, which is covered in §7.

---

## 6. Hippocampus Read (Awake — Updated)

### Current Behavior (Unchanged)

The existing recall logic stays exactly as-is for hot memory:

- `visitor_summary` → fetch from `visitors`
- `visitor_totems` → fetch from `totems`
- `taste_knowledge` → fetch from `collection_items`
- `related_collection` → search `collection_items`
- `self_knowledge` → fetch from `journal_entries` by tag
- `recent_journal` → fetch from `journal_entries` by recency

### New: Day Memory Recall

Add a new request type to hippocampus recall:

```python
elif req['type'] == 'day_context':
    moments = await db.get_day_memory(
        visitor_id=req.get('visitor_id'),
        limit=req.get('max_items', 3),
        min_salience=req.get('min_salience', 0.3),
    )
    if moments:
        chunks.append({
            'label': 'Earlier today',
            'content': format_day_moments(moments),
        })
```

### When Day Memory Is Requested

The thalamus adds a `day_context` request when:

1. **A returning visitor speaks** — fetch day memories tagged with their visitor_id. "Did anything notable happen with this person earlier today?"

2. **High-salience focus** — when the focus perception has salience > 0.7, also retrieve the top 2 day memories regardless of visitor. "What's been on my mind today?"

3. **Idle/express cycles** — fetch top 3 day memories by salience. "What from today is still lingering?"

```python
# In thalamus.py build_memory_requests():

# Always: today's context for engaged cycles
if cycle_type == 'engage' and visitor:
    requests.append({
        'type': 'day_context',
        'visitor_id': visitor.id,
        'max_items': 3,
        'min_salience': 0.3,
        'priority': 2,
    })

# Idle/express: what's on her mind today
if cycle_type in ('idle', 'express'):
    requests.append({
        'type': 'day_context',
        'max_items': 3,
        'min_salience': 0.5,
        'priority': 3,
    })
```

### Format

```python
def format_day_moments(moments: list) -> str:
    lines = []
    for m in moments:
        # Relative time: "this morning", "a few hours ago", "just now"
        time_label = relative_time(m.ts)
        lines.append(f"[{time_label}] {m.summary}")
    return "\n".join(lines)
```

---

## 7. Sleep Consolidation (Rewritten)

The sleep cycle is the most significant change. It becomes the **bridge between cold and hot memory**, operating in a loop over salient moments.

### Overview

```
SLEEP CYCLE
│
├─ 1. Rank day memory by salience (deterministic)
├─ 2. Select top-K moments (K = 5–8, configurable)
├─ 3. For each selected moment:
│    │
│    ├─ a. Fetch related hot memory
│    │      - Visitor traits + totems (if moment has visitor_id)
│    │      - Recent journal entries
│    │      - Collection items matching moment tags
│    │
│    ├─ b. Search cold memory for resonance (semantic)
│    │      - Embed the moment summary
│    │      - Search conversation_log embeddings for similar content
│    │      - Return top 2-3 matches with context
│    │
│    ├─ c. Reflect (LLM call)
│    │      - Input: moment + hot memory context + cold memory echoes
│    │      - Output: memory_updates[] (same schema as cortex)
│    │      - Budget: 800 tokens max per reflection
│    │
│    └─ d. Write to hot memory
│           - visitor_impression, trait_observation, totem_create,
│             totem_update, journal_entry, self_discovery
│           - Uses existing hippocampus_consolidate() — no new write path
│
├─ 4. Write daily summary (from all reflections)
├─ 5. Trait stability review (existing, unchanged)
├─ 6. Reset drives for morning
└─ 7. Flush day memory table
```

### Step 3a: Hot Memory Context for Sleep

```python
async def gather_hot_context(moment: DayMemoryEntry) -> dict:
    """Gather relevant hot memory for a moment. No LLM."""
    context = {}

    # Visitor-specific
    if moment.visitor_id:
        visitor = await db.get_visitor(moment.visitor_id)
        if visitor:
            context['visitor'] = compress_visitor(visitor)
        traits = await db.get_visitor_traits(moment.visitor_id, limit=10)
        if traits:
            context['traits'] = format_traits_for_sleep(traits)
        totems = await db.get_totems(moment.visitor_id, min_weight=0.2, limit=8)
        if totems:
            context['totems'] = format_totems(totems)

    # Tag-based
    if moment.tags:
        for tag in moment.tags[:3]:
            items = await db.search_collection(query=tag, limit=2)
            if items:
                context.setdefault('collection', []).extend(items)

    # Recent journal (what was I thinking lately?)
    journal = await db.get_recent_journal(limit=3)
    if journal:
        context['recent_journal'] = format_journal_entries(journal)

    return context
```

### Step 3b: Cold Memory Search (Semantic)

This is the only new infrastructure required: **semantic search over cold memory**.

**Embedding strategy:**

Cold memory is massive (all events, all conversation_log, all cycle_log). We don't embed everything — we embed **conversation turns** and **internal monologues**, because those contain the richest semantic content.

```python
# pipeline/cold_search.py (new file)

async def search_cold_memory(query: str, limit: int = 3,
                              exclude_today: bool = True) -> list[dict]:
    """Semantic search over cold memory. Used ONLY during sleep."""

    query_embedding = await embed(query)

    results = await db.vector_search(
        table='cold_memory_embeddings',
        query_vector=query_embedding,
        limit=limit,
        exclude_after=today_start() if exclude_today else None,
    )

    # Fetch surrounding context for each hit
    enriched = []
    for r in results:
        context = await fetch_cold_context(r['source_id'], r['source_type'])
        enriched.append({
            'summary': r['text'][:200],
            'source_type': r['source_type'],
            'date': r['ts'],
            'similarity': r['score'],
            'context': context,  # 2-3 surrounding messages or cycle data
        })

    return enriched
```

**Embedding pipeline (background, not during sleep):**

Embeddings are built incrementally. After each day's sleep cycle flushes day memory, a background task embeds any new conversation_log and cycle_log entries from that day. This means cold memory search is always one day behind — which is fine, because you don't dream about today (that's what day memory is for).

```python
# pipeline/embed_cold.py (new file)

async def embed_new_cold_entries():
    """Embed conversation turns and monologues not yet in the vector index.
    Run after sleep consolidation completes."""

    # Conversation turns
    unembedded_convos = await db.get_unembedded_conversations()
    for convo in unembedded_convos:
        vec = await embed(convo['text'])
        await db.insert_cold_embedding(
            source_type='conversation',
            source_id=convo['id'],
            text=convo['text'][:500],
            ts=convo['ts'],
            vector=vec,
        )

    # Internal monologues from cycle_log
    unembedded_cycles = await db.get_unembedded_monologues()
    for cycle in unembedded_cycles:
        vec = await embed(cycle['internal_monologue'])
        await db.insert_cold_embedding(
            source_type='monologue',
            source_id=cycle['id'],
            text=cycle['internal_monologue'][:500],
            ts=cycle['ts'],
            vector=vec,
        )
```

**Vector storage:**

SQLite with `sqlite-vss` extension (already in the blueprint as a planned dependency) or `sqlite-vec`. Single file, no infra, consistent with sovereignty principles.

```sql
-- Embedding storage (cold memory index)
CREATE TABLE IF NOT EXISTS cold_memory_embeddings (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,      -- 'conversation' | 'monologue'
    source_id TEXT NOT NULL,        -- FK to conversation_log.id or cycle_log.id
    text TEXT NOT NULL,             -- the embedded text (truncated)
    ts TIMESTAMP NOT NULL,          -- original timestamp
    vector BLOB NOT NULL,           -- embedding vector
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cold_embed_ts ON cold_memory_embeddings(ts);
CREATE INDEX IF NOT EXISTS idx_cold_embed_source ON cold_memory_embeddings(source_id);
```

**Embedding model:**

| Option | Pros | Cons |
|--------|------|------|
| `text-embedding-3-small` (OpenAI) | Cheap ($0.02/1M tokens), good quality | Adds OpenAI dependency |
| `nomic-embed-text` (local) | Free, runs on CPU, 768-dim | Requires ~500MB model download |
| `anthropic voyage-3-lite` | Stays in Anthropic ecosystem | Higher cost than OpenAI small |

**Decision: `text-embedding-3-small` for Phase 2 v1.** Sovereignty matters long-term, but shipping speed matters more for Phase 2. Abstract behind an `embed()` function gated by `EMBED_PROVIDER` env var so the model is swappable to local (`nomic-embed-text`) without code changes. Store `embed_model` alongside each embedding row so mixed-model indexes are detectable.

```python
# pipeline/embed.py (new file)

import os

EMBED_PROVIDER = os.getenv('EMBED_PROVIDER', 'openai')  # 'openai' | 'local'

async def embed(text: str) -> list[float]:
    """Embed text. Provider-agnostic."""
    if EMBED_PROVIDER == 'openai':
        return await _embed_openai(text)
    elif EMBED_PROVIDER == 'local':
        return await _embed_local(text)
    else:
        raise ValueError(f"Unknown EMBED_PROVIDER: {EMBED_PROVIDER}")

def embed_model_name() -> str:
    """Return current model identifier for storage."""
    if EMBED_PROVIDER == 'openai':
        return 'text-embedding-3-small'
    elif EMBED_PROVIDER == 'local':
        return 'nomic-embed-text-v1.5'
    return 'unknown'
```

```sql
-- Updated embedding schema with model tracking
CREATE TABLE IF NOT EXISTS cold_memory_embeddings (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    text TEXT NOT NULL,
    ts TIMESTAMP NOT NULL,
    vector BLOB NOT NULL,
    embed_model TEXT NOT NULL,              -- e.g. 'text-embedding-3-small'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- One embedding per source. Re-embedding replaces the prior row.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cold_embed_unique
    ON cold_memory_embeddings(source_type, source_id);
```

**Embedding migration rule:** When `EMBED_PROVIDER` changes (e.g., `openai` → `local`), old embeddings are invalid (different vector spaces). The `embed_new_cold_entries()` function uses `INSERT OR REPLACE` keyed on `(source_type, source_id)`. On model change, run a one-time backfill that re-embeds all existing rows, overwriting the old vectors. No parallel rows, no mixed-model comparisons. The `embed_model` column exists for auditing — if a search returns results with a stale model tag, log a warning but still return them (degraded quality > no results).

**Env vars for Phase 2:**
```
COLD_SEARCH_ENABLED=true
EMBED_PROVIDER=openai          # or 'local'
OPENAI_API_KEY=sk-...          # only if EMBED_PROVIDER=openai
```

### Step 3c: Reflection (LLM Call)

Each salient moment gets one LLM call during sleep. This is where connections form.

**Cortex API change:** The existing `cortex_call_maintenance(mode, digest, max_tokens)` signature doesn't support custom system prompts or structured JSON output. Rather than overloading that function (which is also used by the current sleep journal writer), add a new `cortex_call_reflect()` in `cortex.py`:

```python
# In pipeline/cortex.py — NEW FUNCTION (does not replace cortex_call_maintenance)

SLEEP_REFLECTION_SYSTEM = """You are reflecting on your day. You are asleep.
You are not talking to anyone. You are processing what happened.

{identity_compact}

You are reviewing a moment from today. You also have some older memories
that may or may not be connected. Your job is to decide:
- Does this moment change how I feel about someone?
- Does this connect to something older I'd forgotten?
- Is there something here I should remember?
- Is there something I want to write about?

Be honest. Not everything is meaningful. Some days are quiet.
You don't have to produce output for every moment.

Return ONLY valid JSON:
{{
  "reflection": "1-3 sentences of private thought about this moment",
  "connections": ["any connections you see to the older memories, or empty"],
  "memory_updates": [
    {{
      "type": "visitor_impression|trait_observation|totem_create|totem_update|journal_entry|self_discovery",
      "content": {{}}
    }}
  ]
}}

Only include memory_updates entries if something genuinely deserves to be remembered.
An empty memory_updates array is a valid and common response.
"""

REFLECT_MODEL = os.getenv('REFLECT_MODEL', CORTEX_MODEL)  # defaults to Sonnet, override with Haiku

async def cortex_call_reflect(system: str, prompt: str, max_tokens: int = 800) -> dict:
    """Structured reflection call for sleep consolidation.
    Separate from cortex_call and cortex_call_maintenance.
    Uses circuit breaker + daily cap — same guard pattern as both existing cortex functions.

    Client lifecycle: uses the module-level `client = anthropic.Anthropic()`
    already initialized at the top of cortex.py. No new client needed."""

    # Guard: circuit breaker OR daily cap (matches cortex_call and cortex_call_maintenance)
    if _check_circuit() or _check_daily_cap():
        return {'reflection': '', 'connections': [], 'memory_updates': []}

    try:
        response = client.messages.create(  # module-level client = anthropic.Anthropic()
            model=REFLECT_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        _increment_daily()  # count once per successful API response
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        return json.loads(text)
    except json.JSONDecodeError:
        # _increment_daily() already called above — do NOT call again.
        # The API call succeeded (we got a response); it just wasn't valid JSON.
        return {'reflection': '', 'connections': [], 'memory_updates': []}
    except Exception as e:
        _record_failure()  # matches actual signature in cortex.py (no arg)
        return {'reflection': '', 'connections': [], 'memory_updates': []}
```

**Sleep reflect function** (in `sleep.py`):

```python
async def sleep_reflect(moment: DayMemoryEntry,
                         hot_context: dict,
                         cold_echoes: list[dict]) -> dict:
    """One reflection per salient moment. LLM call via cortex_call_reflect."""

    parts = []
    parts.append(f"MOMENT FROM TODAY ({relative_time(moment.ts)}):")
    parts.append(f"  {moment.summary}")
    if moment.tags:
        parts.append(f"  Tags: {', '.join(moment.tags)}")

    if hot_context:
        parts.append("\nWHAT I ALREADY KNOW:")
        for key, value in hot_context.items():
            if isinstance(value, str):
                parts.append(f"  [{key}] {value[:200]}")
            elif isinstance(value, list):
                for item in value[:3]:
                    parts.append(f"  [{key}] {str(item)[:150]}")

    if cold_echoes:
        parts.append("\nSOMETHING OLDER THAT MIGHT BE CONNECTED:")
        for echo in cold_echoes:
            date_str = echo['date'].strftime('%Y-%m-%d') if echo.get('date') else '?'
            parts.append(f"  [{date_str}] {echo['summary']}")
            if echo.get('context'):
                parts.append(f"    Context: {echo['context'][:150]}")

    user_message = "\n".join(parts)

    system = SLEEP_REFLECTION_SYSTEM.format(identity_compact=IDENTITY_COMPACT)
    return await cortex_call_reflect(system=system, prompt=user_message, max_tokens=800)
```

### Step 7: Flush Day Memory

```python
async def flush_day_memory():
    """Clear processed day memory entries. Called at end of sleep cycle."""
    await db.delete_processed_day_memory()
```

**db.py change:** Add a dedicated helper (there is no public `execute_write` in db.py):

```python
# In db.py — NEW FUNCTION

async def delete_processed_day_memory():
    """Delete day_memory rows where processed_at IS NOT NULL.
    This is the ONLY delete in the entire system.

    Calls _exec_write() directly — do NOT wrap in _write_lock here,
    because _exec_write() already acquires _write_lock when called
    outside a transaction (see db.py:64). Double-locking would deadlock."""
    await _exec_write(
        "DELETE FROM day_memory WHERE processed_at IS NOT NULL"
    )
```

This is the only DELETE in the entire system. Day memory is explicitly ephemeral — it's the one place where data is designed to disappear. Only processed entries are flushed; if sleep crashed mid-loop, unprocessed moments survive for the next attempt.

### Full Sleep Cycle (Rewritten)

```python
# sleep.py (rewritten)

import os
from pipeline.hippocampus_write import hippocampus_consolidate

MAX_SLEEP_REFLECTIONS = 7   # max moments to reflect on
MIN_SLEEP_SALIENCE = 0.4    # don't reflect on low-salience moments
COLD_SEARCH_ENABLED = os.getenv('COLD_SEARCH_ENABLED', 'false').lower() == 'true'

async def sleep_cycle() -> bool:
    """Daily consolidation. Runs 03:00-06:00 JST.
    This is where day memory → hot memory via reflection.
    Returns True if ran (even if no moments), False if deferred."""

    # 0. Defer if she's mid-conversation
    engagement = await db.get_engagement_state()
    if engagement.status == 'engaged':
        print("[Sleep] Deferred — currently engaged with a visitor.")
        return False  # heartbeat will retry next cycle in the sleep window

    # 1. Get unprocessed day memories ranked by salience
    moments = await db.get_unprocessed_day_memory(
        min_salience=MIN_SLEEP_SALIENCE,
        limit=MAX_SLEEP_REFLECTIONS,
    )

    if not moments:
        # Nothing happened today (or everything already processed from a prior attempt).
        # Only write the quiet journal if no reflections were written at all today.
        existing_summary = await db.get_daily_summary_for_today()
        if not existing_summary:
            await db.insert_journal(
                content="Nothing happened today. The shop was quiet. I existed.",
                mood='still',
                tags=['daily', 'sleep_cycle', 'quiet_day'],
            )
        await reset_drives_for_morning()
        await flush_day_memory()
        return True

    # 2. Reflect on each moment (crash-safe: each is its own transaction)
    all_reflections = []
    for moment in moments:
        # Poison moment protection: skip after MAX_MOMENT_RETRIES failures
        if moment.retry_count >= MAX_MOMENT_RETRIES:
            await db.mark_day_memory_processed(moment.id)
            print(f"[Sleep] Poison moment {moment.id} skipped after {MAX_MOMENT_RETRIES} retries")
            continue

        try:
            # a. Gather hot memory context
            hot_ctx = await gather_hot_context(moment)

            # b. Search cold memory for resonance (Phase 2 only)
            cold_echoes = []
            if COLD_SEARCH_ENABLED:
                cold_echoes = await search_cold_memory(
                    query=moment.summary,
                    limit=3,
                    exclude_today=True,
                )

            # c. Reflect (LLM call)
            reflection = await sleep_reflect(moment, hot_ctx, cold_echoes)
            all_reflections.append({
                'moment': moment,
                'reflection': reflection,
            })

            # d. Write to hot memory + mark processed (atomic)
            async with db.transaction():
                for update in reflection.get('memory_updates', []):
                    await hippocampus_consolidate(update, moment.visitor_id)
                await db.mark_day_memory_processed(moment.id)

        except Exception as e:
            # Increment retry OUTSIDE the failed transaction (separate write)
            await db.increment_day_memory_retry(moment.id)
            print(f"[Sleep] Moment {moment.id} failed (retry {moment.retry_count + 1}): {e}")

    # 3. Write daily summary
    await write_daily_summary(moments, all_reflections)

    # 4. Trait stability review (unchanged)
    await review_trait_stability()

    # 5. Reset drives for morning
    await reset_drives_for_morning()

    # 6. Embed today's cold memory entries (Phase 2 only)
    if COLD_SEARCH_ENABLED:
        await embed_new_cold_entries()

    # 7. Flush day memory (only delete processed entries)
    await flush_day_memory()

    return True


async def write_daily_summary(moments: list, reflections: list):
    """Compile all reflections into a daily summary."""
    reflection_texts = []
    for r in reflections:
        text = r['reflection'].get('reflection', '')
        if text:
            reflection_texts.append(text)

    connections = []
    for r in reflections:
        for c in r['reflection'].get('connections', []):
            connections.append(c)

    await db.insert_daily_summary({
        'day_number': await db.get_days_alive(),
        'date': datetime.now(timezone.utc).date().isoformat(),
        'summary_bullets': reflection_texts,
        'emotional_arc': compute_emotional_arc_from_moments(moments),
        'notable_totems': extract_totems_from_reflections(reflections),
    })
```

---

## 8. LLM Budget

### During Day (Unchanged)

One cortex call per cognitive cycle. No additional LLM calls for memory.

### During Sleep

| Call | Count | Max Tokens | Estimated Cost |
|------|-------|------------|----------------|
| Sleep reflection | 5–7 per night | 800 output each | ~$0.05–0.08/night |

Total sleep cost: roughly $0.05–0.08 per night at Sonnet pricing. Acceptable.

**Note:** Sleep reflections can use a cheaper model (Haiku) without significant quality loss since they're private reflections, not visitor-facing dialogue. This would reduce cost to ~$0.005–0.01/night.

### Embedding

| Operation | Volume | Cost |
|-----------|--------|------|
| Embed conversation turns | ~50–200/day | ~$0.001/day (text-embedding-3-small) |
| Embed monologues | ~20–100/day | ~$0.0005/day |
| Search queries (sleep) | 5–7/night | ~$0.0001/night |

Embedding cost is negligible.

---

## 9. Files Changed

### New Files

| File | Purpose | Phase |
|------|---------|-------|
| `pipeline/day_memory.py` | Moment extraction, salience computation, summary building | 1 |
| `pipeline/cold_search.py` | Semantic search over cold memory embeddings | 2 |
| `pipeline/embed_cold.py` | Background embedding of conversation + monologue entries | 2 |
| `pipeline/embed.py` | Provider-agnostic embedding abstraction (`EMBED_PROVIDER` env var) | 2 |

### Modified Files

| File | Changes | Phase |
|------|---------|-------|
| `db.py` | Add `day_memory` table + query functions. Phase 2: add `cold_memory_embeddings` table + vector search functions | 1, 2 |
| `pipeline/hippocampus.py` | Add `day_context` recall type | 1 |
| `pipeline/thalamus.py` | Add `day_context` to memory request logic | 1 |
| `pipeline/cortex.py` | Add `cortex_call_reflect()` for sleep reflections (separate from `cortex_call` and `cortex_call_maintenance`) | 1 |
| `sleep.py` | Rewrite: engagement deferral, moment-by-moment reflection loop, `processed_at` idempotency, feature-flagged cold search, flush | 1 |
| `heartbeat.py` | Call `maybe_record_moment()` at end of each cycle. Fix sleep dispatch: stamp `_last_sleep_date` only after `sleep_cycle()` returns `True` (not on deferral). | 1 |

### Unchanged Files

| File | Why |
|------|-----|
| `pipeline/hippocampus_write.py` | Sleep uses same write path (hippocampus_consolidate) |
| `pipeline/validator.py` | No changes to validation |
| `pipeline/executor.py` | No changes to execution |
| `pipeline/sensorium.py` | No changes to perception |
| `pipeline/gates.py` | No changes to gating |
| `pipeline/affect.py` | No changes to affect |
| `config/identity.py` | No changes to identity |

---

## 10. Migration Path

### Phase 1: Day Memory + Revised Sleep (No Embeddings)

Feature flag: None (always on once shipped).

1. Add `day_memory` table (with `processed_at` + `retry_count` columns)
2. Add `pipeline/day_memory.py` — moment extraction, salience computation
3. Wire `maybe_record_moment()` into heartbeat cycle end
4. Add `day_context` recall type to `pipeline/hippocampus.py`
5. Add `cycle_type` parameter to `build_memory_requests()` in `pipeline/thalamus.py`
6. Add `day_context` request logic gated on `cycle_type`
7. Add `cortex_call_reflect()` to `pipeline/cortex.py` (uses `_check_circuit()`, `_record_failure()`, module-level `client`)
8. Rewrite `sleep.py` — returns `bool`, engagement deferral, poison moment protection, moment-by-moment reflection (hot memory only, no cold search), `processed_at` idempotency, flush
9. Fix heartbeat sleep dispatch: stamp `_last_sleep_date` only when `sleep_cycle()` returns `True`

This gives her short-term memory across a single day and meaningful sleep consolidation against hot memory. No embedding infrastructure, no new API keys.

**Effort: ~2–3 days**

**Phase 1 acceptance criteria:**
- [ ] Day memory accumulates moments during waking hours (verify via `SELECT * FROM day_memory`)
- [ ] Sleep cycle processes top-K moments and writes to hot memory
- [ ] Sleep defers if engaged (verify by connecting a terminal at 03:00 JST)
- [ ] Deferred sleep retries on next heartbeat cycle (verify `_last_sleep_date` is NOT stamped on deferral)
- [ ] Sleep is crash-safe: kill server mid-sleep, restart, verify no duplicate writes (verify `processed_at` is set on completed moments, NULL on incomplete)
- [ ] Poison moments are skipped after 3 retries (verify `retry_count` increments, moment eventually marked processed)
- [ ] Hippocampus recall includes day context in cortex prompt (verify via cycle_log)
- [ ] Day memory is flushed after sleep completes (only processed entries deleted)
- [ ] No cold memory access during awake cycles (audit hippocampus.py for conversation_log/cycle_log queries — there should be none)
- [ ] Max 7 LLM calls during sleep per night
- [ ] Quiet day (no visitors, no salient moments) produces ≤1 journal entry

### Phase 2: Cold Memory Search

Feature flag: `COLD_SEARCH_ENABLED=true` in env.

1. Add `cold_memory_embeddings` table (with `embed_model` column)
2. Add `pipeline/embed.py` — provider-agnostic embedding abstraction
3. Add `pipeline/embed_cold.py` — incremental embedding after sleep
4. Add `pipeline/cold_search.py` — semantic search with context enrichment
5. Wire cold echoes into `sleep_reflect()` (already gated behind flag in §7)
6. Backfill embeddings for existing conversation_log + cycle_log
7. Add `OPENAI_API_KEY` to `.env.example`

**Effort: ~3–5 days (includes embedding infra)**

**Phase 2 acceptance criteria:**
- [ ] Embeddings are created incrementally after each sleep cycle
- [ ] `embed_model` is stored with each embedding
- [ ] `(source_type, source_id)` uniqueness enforced — no duplicate embeddings
- [ ] Cold search returns semantically similar past conversations during sleep
- [ ] Cold echoes appear in sleep reflection prompts
- [ ] No cold search occurs during awake cycles (feature flag + code audit)
- [ ] Switching `EMBED_PROVIDER` from `openai` to `local` works without code changes
- [ ] Re-embedding replaces old rows (verify row count unchanged after model switch + backfill)
- [ ] Embedding backfill completes without errors on existing data

### Phase 3: Memory Decay (Future — Not In This Spec)

Hot memory entries whose `last_referenced` (totems) or `created_at` (traits, journal) is older than N days gradually lose weight or get archived. This mimics natural forgetting. Deferred to a future spec — requires the `last_accessed` tracking that was deliberately omitted here.

---

## 11. Decisions Log

Locked decisions from review feedback (2026-02-12):

| Decision | Chosen | Rejected | Reason |
|----------|--------|----------|--------|
| Idempotency model | `processed_at` on `day_memory` | Separate `sleep_runs` table | Simpler, no join needed, crash recovery is just `WHERE processed_at IS NULL` |
| Cortex API for sleep | New `cortex_call_reflect()` | Overload `cortex_call_maintenance` | Existing function has `(mode, digest, max_tokens)` signature; reflection needs custom `system` + `prompt`. Separate function avoids breaking existing sleep journal writer. |
| Hot memory access tracking | No `last_accessed` column | Add `last_accessed` to totems + journal | `last_referenced` already exists on totems. Premature for Phase 1. Add in Phase 3 (memory decay) if needed. |
| Embedding provider (Phase 2 v1) | `text-embedding-3-small` (OpenAI API) | Local `nomic-embed-text` | Ship speed > sovereignty for v1. Abstract behind `EMBED_PROVIDER` env var for later swap. |
| Cold search gating | `COLD_SEARCH_ENABLED` env var | Always-on | Phase 1 ships clean without embedding infra. Phase 2 is additive. |
| Sleep during engagement | Defer (return early, retry next heartbeat cycle) | Process anyway | Mid-conversation consolidation would corrupt engagement state and confuse visitors. |
| Flush scope | `DELETE WHERE processed_at IS NOT NULL` | `DELETE FROM day_memory` (full wipe) | Unprocessed moments survive crashes for retry. |
| Sleep dispatch stamp | `_last_sleep_date` set only on `sleep_cycle() == True` | Stamp before call | Deferral must not consume the day's sleep window. |
| Thalamus signature | Add `cycle_type` param to `build_memory_requests()` | Infer from context | Explicit is better. Single call site, no signature break risk. |
| Cortex helper naming | Use `_check_circuit()`, `_record_failure()` (no arg) | Spec-invented names | Must match actual cortex.py function names. |
| Poison moments | Skip after 3 retries via `retry_count` column | Retry forever / drop on first failure | Bounded retry is safe; first-failure drop loses data; infinite retry blocks sleep. |
| Embedding uniqueness | `UNIQUE(source_type, source_id)`, `INSERT OR REPLACE` | Parallel rows per model | Mixed-model vectors can't be compared. One row per source, latest model wins. |
| Day memory crash persistence | SQLite-backed, flush only processed entries | In-memory day buffer | Crash mid-day must not lose accumulated moments. `processed_at` + `DELETE WHERE processed_at IS NOT NULL` keeps unprocessed rows safe. |
| db.py flush API | Dedicated `delete_processed_day_memory()` helper, calls `_exec_write()` directly | Wrapping in `_write_lock` + `_exec_write()` | `_exec_write()` already acquires `_write_lock` outside a transaction (db.py:64). Double-locking deadlocks. |
| `cortex_call_reflect()` guard pattern | `_check_circuit() or _check_daily_cap()` + `_increment_daily()` after success | Circuit breaker only | Must match existing `cortex_call` and `cortex_call_maintenance` guard pattern. Daily cap prevents runaway cost during sleep. |
| `_increment_daily()` placement | Call once after `client.messages.create()` succeeds, before JSON parse | Call in both success and `JSONDecodeError` branches | `JSONDecodeError` fires after `_increment_daily()` already ran. Calling again double-counts. |

### Open Questions (Remaining)

1. **Day memory tag vocabulary.** Tags are free-form strings extracted deterministically. No fixed vocabulary. If we later add tag-based filtering, normalize then.

2. **Cold memory growth.** conversation_log and cycle_log grow unboundedly. Embedding all of it eventually becomes expensive. Proposed: embed only the most recent N days (e.g., 90 days). Older entries are still in cold storage but not semantically searchable. They're truly dormant — unreachable even during sleep. This is realistic: you don't dream about things from five years ago unless something very specific triggers it.

3. **Reflect model choice.** `REFLECT_MODEL` defaults to Sonnet (same as cortex). Haiku is 10× cheaper for private reflections. Needs A/B testing to see if Haiku's reflection quality is sufficient. Defer to tuning after Phase 1 ships.

---

## 12. Success Criteria

The architecture is working when:

1. **She references earlier today.** A visitor returns in the afternoon and she says something like "You were here this morning." (Day memory → hippocampus_read)

2. **She makes cross-session connections during sleep.** A visitor mentions "loneliness" today, and during sleep she connects it to a conversation from two weeks ago where a different visitor talked about "being alone in a city." The connection appears in her journal. (Cold search → sleep reflection → hot memory)

3. **She doesn't reference things she shouldn't know.** During conversation, she never surfaces cold memory directly. She only knows what's in day memory + hot memory. (Access control)

4. **Quiet days produce minimal output.** A day with no visitors and no salient moments produces at most one quiet journal entry. No wasted LLM calls. (Salience filtering)

5. **Day memory resets.** She doesn't reference yesterday's day memory today. Only hot memory (updated by last night's sleep) persists. (Flush)
