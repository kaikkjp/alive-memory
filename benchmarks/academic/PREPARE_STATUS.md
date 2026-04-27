# Academic Benchmark Prepare Status

Last updated: 2026-04-27

## Prepared Locally

| Benchmark | System | Status | Location |
|-----------|--------|--------|----------|
| LoCoMo | `alive` | 10/10 instances prepared | `benchmarks/academic/prepared/locomo/alive` |
| LongMemEval-S | `alive` | 8/500 instances prepared, resumable | `benchmarks/academic/prepared/longmemeval/alive` |
| MemoryArena | `alive` | 4850/4850 instances prepared | `benchmarks/academic/prepared/memoryarena/alive` |

LongMemEval was stopped intentionally because local ingestion is CPU-bound and
the full 500-instance prepare is a multi-hour job in the current environment.
Resume it with:

```bash
.venv/bin/python -m benchmarks.academic prepare \
    --benchmark longmemeval \
    --system alive \
    --workers 4 \
    --resume
```

If the machine has more free cores and memory, increase `--workers`. The saved
instance directories are atomic; `--resume` skips any instance with a
`meta.json`.

## Dataset State

| Benchmark | Dataset State |
|-----------|---------------|
| LoCoMo | Downloaded to `benchmarks/academic/data/locomo/locomo10.json` |
| LongMemEval-S | Available through `benchmarks/academic/data/longmemeval/longmemeval_s_cleaned.json` |
| MemoryAgentBench | Adapter implemented for normalized local JSON and public Hugging Face rows at `ai-hyz/MemoryAgentBench`. Full local prepare not run. Smoke prepare passed with `ALIVE_BENCH_HF_MAX_ROWS=1 ALIVE_BENCH_MAX_CONTEXT_CHUNKS=2`. |
| MemoryArena | Adapter implemented for normalized local JSON and public Hugging Face JSONL at `ZexueHe/memoryarena`. Full local prepare completed for 4850/4850 instances. |

## Synthetic Benchmark Streams

Prepared under `benchmarks/data`:

| Stream | Events | Query Files |
|--------|--------|-------------|
| `research_assistant_10k` | 10,000 | `research_assistant_queries.jsonl`, `research_assistant_gt.jsonl` |
| `customer_support_5k` | 5,000 | `customer_support_queries.jsonl`, `customer_support_gt.jsonl` |
| `personal_assistant_15k` | 15,000 | `personal_assistant_queries.jsonl`, `personal_assistant_gt.jsonl` |
| `autobiographical_agent_3k` | 3,000 | `autobiographical_agent_queries.jsonl`, `autobiographical_agent_gt.jsonl` |
| `stress_test_50k` | 50,000 | `stress_test_queries.jsonl`, `stress_test_gt.jsonl` |

`stress_test` now writes its own stream/query/ground-truth filenames, so it no
longer overwrites `research_assistant` ground truth.

`autobiographical_agent_3k` now includes Track E axis metadata on queries and
ground truth. The benchmark runner writes `autobiographical_summary` and
`autobiographical_scores` into result JSON, and the report generator renders an
Autobiographical Memory scorecard. Result JSON also includes `run_manifest`
dataset hashes and `recall_traces` with retrieved snippets, scores, timestamps,
tiers, and adapter-provided evidence ids.

## Fixes Before Full Benchmark

Do these before spending full LongMemEval-scale runtime or API budget:

1. Calibrate and manually audit the `autobiographical_agent_3k` evaluator. The
   initial deterministic scorer is implemented, but the ground truth still
   needs human review before publication-grade claims.
2. Decide the MemoryAgentBench context budget before full prepare. Its public
   rows contain very large context strings, so use the full context for
   publication runs and `ALIVE_BENCH_MAX_CONTEXT_CHUNKS` only for adapter smoke
   tests unless the capped budget is explicitly registered.
3. Freeze the competitor manifest. Decide whether Mastra is tested through a
   direct adapter, an observation-log equivalent, or listed only as an external
   reference. Do the same for Mem0, Zep/Graphiti, and MemGPT/Letta-style memory.
4. Extend the generated run manifest with model names, prompts, adapter
   versions, config, hardware, context budget, token budget, latency budget,
   and storage budget. Dataset hashes, counts, seeds, and git SHA are already
   recorded by the harness.
5. Confirm recall traces are complete for every adapter. The runner saves
   snippets, scores, timestamps, tiers, and adapter-provided evidence ids; any
   missing memory ids/evidence ids are adapter gaps.
6. Smoke-test every configured baseline after installing optional dependencies
   and before starting long runs.
7. Add cost and footprint capture to every result: ingest latency, recall
   latency, consolidation latency, answer latency, tokens, estimated cost,
   stored-memory count, and disk size.
8. Manually audit synthetic ground truth for current-vs-superseded preferences
   and emotionally important-vs-repeated memories.

## Environment Blockers

The current virtualenv can run alive-memory with local embeddings, but the
optional benchmark baselines are not installed:

- `chromadb` and `sentence-transformers` for RAG
- `anthropic`, `openai`, or an OpenRouter-compatible key for answer generation
- `mem0ai` for Mem0
- `zep-cloud` for Zep

Install benchmark extras before running full comparison baselines:

```bash
.venv/bin/pip install -r benchmarks/requirements.txt
```

No LLM API key was present in this shell during preparation. The prepare phase
can still build alive-memory state locally, but the bench phase needs an answer
model unless you configure a compatible local endpoint.

## One-Command Prepare

Use this to prepare every academic dataset that is locally available and skip
missing/unadapted datasets with explicit reasons:

```bash
.venv/bin/python -m benchmarks.academic prepare-all \
    --system alive \
    --workers 4 \
    --resume
```
