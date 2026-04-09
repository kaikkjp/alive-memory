# LongMemEval Benchmark Analysis — 2026-03-23

## Results Summary

| Run | Accuracy | F1 | Notes |
|---|---|---|---|
| Baseline (main) | 37.8% | 17.1% | run_1774131795 |
| v3 before recall fix | 35.4% | 16.1% | run_1774218899 |
| v3 after recall fix | 43.2% | 18.0% | run_1774227425, ranked grep + raised limits + diversity |

### Per-category (v3 after recall fix vs baseline)

| Category | Baseline | After Fix | Delta |
|---|---|---|---|
| information_extraction | 58.9% | 66.0% | +7.1 |
| knowledge_updates | 47.6% | 65.3% | +17.7 |
| multi_session_reasoning | 32.4% | 29.8% | -2.6 |
| temporal_reasoning | 15.9% | 25.2% | +9.3 |
| abstention | 0.0% | 6.7% | +6.7 |

## Root Causes Found

### 1. Totem extraction prompt produces vague summaries, not facts

**File:** `alive_memory/consolidation/reflection.py:98-134`

The prompt asks for `"context": brief context explaining relevance` and uses system prompt
`"You are a reflective mind processing experiences."` This causes the LLM to produce
topic-level descriptions instead of specific facts.

**Evidence:** Of 1,085 totems in instance_000, only 31 (3%) contain numeric values.

```
OLD: "blood pressure — Managing blood pressure is a significant aspect of my health journey"
OLD: "Fitbit Inspire HR — A fitness tracker that helps monitor progress"
```

A re-extraction with a better prompt on the same data produced 964 totems with 268 (28%)
containing numbers:

```
NEW: "blood pressure monitor — User purchased a wireless blood pressure monitor from Omron on March 10th"
NEW: "Fitbit Inspire HR — User has invested in a Fitbit Inspire HR for tracking progress"
NEW: "Luna's pet bed — The original price of Luna's pet bed was $40"
NEW: "foam roller — Purchased from Amazon, arrived on March 2nd"
```

**Cost impact:** ~$300 spent across 4 prepare runs all producing garbage totems due to this
single prompt. Re-extraction with fixed prompt costs ~$44 for all 500 instances.

### 2. Consolidation drops original conversation timestamps

**File:** `alive_memory/consolidation/__init__.py:380-384`

The dataset provides per-session dates (e.g. `"2023/05/20 (Sat) 02:21"`). The benchmark
adapter correctly passes them as `metadata["timestamp"]` on each moment. But consolidation
writes to cold_memory with only `event_type`, `valence`, and `salience` in the metadata dict:

```python
# consolidation/__init__.py:380-384
metadata={
    "event_type": moment.event_type.value,
    "valence": moment.valence,
    "salience": moment.salience,
},
```

The original conversation date is **silently dropped**. All cold_memory entries get
`created_at = 2026-03-20T08:58` (consolidation wallclock time). Totem `first_seen_at`
is also set to `datetime.now()` instead of the original conversation date.

**Impact:** temporal_reasoning accuracy is 25.2% — the system cannot answer "how many days
since X?" because it has no temporal data. 64.6% of temporal questions get "I don't know".

### 3. Batch reflection truncates moment content to 300 chars

**File:** `alive_memory/consolidation/reflection.py:183`

```python
batch_text = "\n".join(
    f"[{i+1}] ({m.event_type.value}, salience={m.salience:.2f}) {m.content[:300]}"
    for i, m in enumerate(moments)
)
```

Medium and low salience moments (the majority — typically ~500 out of ~550) are truncated
to 300 characters before the LLM sees them. Specific details like exact amounts, dates,
and names at the end of longer turns are lost before extraction even begins.

### 4. Abstention scoring bug — metadata dropped during serialization

**File:** `benchmarks/academic/parallel_run.py:167` (FIXED in this commit)

`_serialize_instances()` only serialized `query_id`, `answer`, `category` — dropping
`metadata` (which contains `is_abstention`) and `evidence`. When bench deserializes with
`GroundTruth(**v)`, `metadata` defaults to `{}`, so `is_abstention` is always `False`.

The system correctly says "I don't know" for 25/30 abstention questions but scores 0.0
because it's compared token-by-token against the expected answer instead of using the
abstention scorer.

**Impact:** Fixing this requires re-prepare since the broken metadata is baked into
prepared meta.json files. Expected lift: ~4-5% accuracy.

### 5. Keyword grep was unranked and noise-saturated

**Files:** `alive_memory/hot/reader.py`, `alive_memory/recall/hippocampus.py` (FIXED in this commit)

The grep used ANY-match semantics — a query like "What did Alice say about her Paris trip?"
matched every line containing "what", "about", "her", etc. Results were returned in file
order (newest first) without relevance scoring, consuming the limit=30 budget with noise.

`score_grep_result()` existed in `recall/weighting.py` but was **never called**.

**Fixes applied:**
- Stopword filtering to avoid matching common words
- Keyword density scoring (fraction of distinct query keywords in context)
- Round-robin diversity across source files for multi-session coverage
- Raised grep pool from `limit*3` to `limit*5`
- Raised cold search limit from `limit` to `limit*2`
- Lowered cold min_score from 0.3 to 0.15
- Raised recall default_limit from 10 to 20
- Raised context slice caps in benchmark adapter

### 6. Dreams produce narrative prose, no structured output

**File:** `alive_memory/consolidation/dreaming.py`

Dreams are meant to connect today's salient moments with distant cold memory facts.
Currently they produce 2-3 sentence prose insights written to reflections/.
No totems, no temporal facts, no structured output. The prompt asks for "meaningful
connections" and "patterns" — the LLM produces philosophy.

For the benchmark, this has zero value. Multi-session reasoning and temporal reasoning
need structured facts about what changed across sessions, not prose.

## Architectural Insight

Leading LongMemEval systems (e.g. Mastra.ai) use 2+ write-time agents that observe
conversations in real-time, extracting facts and curating structured context on the fly.
At query time, there is no recall/search step — the answer is already in a pre-built
document. Our system does extraction as a deferred batch (consolidation/sleep) with a
prompt that produces vague summaries. The gap is fundamental: write-time curation vs
read-time search.

## Fixes Remaining (consolidation pipeline)

1. **Fix timestamp passthrough** — include `moment.metadata.get("timestamp")` in
   cold_memory metadata and totem `first_seen_at`
2. **Fix extraction prompts** — replace "brief context explaining relevance" with
   "specific fact with exact values", add BAD/GOOD examples, change system prompt
3. **Remove batch truncation** — or raise significantly from 300 chars
4. **Fix dreams** — produce structured temporal/update totems, not prose
