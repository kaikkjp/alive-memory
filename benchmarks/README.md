# alive-memory Benchmark Framework

Longitudinal benchmarks comparing agent memory systems over thousands of cycles.

alive-memory should be benchmarked as **autobiographical, identity-preserving,
emotionally weighted memory for persistent agents**. Generic recall scores are
required, but they are not sufficient. A run that improves LongMemEval while
breaking stable self-identity, visitor tastes, affective salience, or
person-boundary isolation is a product regression.

## Quick Start

```bash
# Install dependencies
pip install -r benchmarks/requirements.txt

# Generate benchmark data (no API key needed — template-based)
python -m benchmarks generate --scenario research_assistant

# Run a quick sanity check (alive vs RAG, 1000 cycles)
python -m benchmarks run --stream research_assistant_10k --systems alive,rag --max-cycles 1000

# Run full benchmark with multiple seeds
python -m benchmarks run --stream research_assistant_10k --all --seeds 42,123,456,789,1337

# Generate report
python -m benchmarks report --results-dir benchmarks/results/ --charts
```

## Academic Benchmarks (Two-Phase Workflow)

For academic benchmarks (LongMemEval, LoCoMo, etc.), use the two-phase
**prepare/bench** workflow. This separates expensive consolidation from
cheap query evaluation, so you can iterate on recall strategies without
re-running consolidation.

```bash
# Phase 1: PREPARE — ingest + consolidate + save state (expensive, run once)
python -m benchmarks.academic prepare \
    --benchmark longmemeval --system alive --workers 16

# Phase 2: BENCH — load saved state + run queries (cheap, run many times)
python -m benchmarks.academic bench \
    --benchmark longmemeval \
    --prepared-dir benchmarks/academic/prepared/longmemeval/alive \
    --workers 16
```

To prepare every academic dataset that is present locally, use:

```bash
python -m benchmarks.academic prepare-all \
    --system alive --workers 4 --resume
```

`prepare-all` skips missing datasets by default and prints the exact download
or adapter blocker. MemoryAgentBench and MemoryArena now support public
Hugging Face formats directly through the standard library:

- MemoryAgentBench: `ai-hyz/MemoryAgentBench` via dataset-server row JSON
- MemoryArena: `ZexueHe/memoryarena` via public JSONL files

For adapter smoke tests, set `ALIVE_BENCH_HF_MAX_ROWS=1`. For
MemoryAgentBench only, `ALIVE_BENCH_MAX_CONTEXT_CHUNKS=N` can cap context
chunks so the prepare path can be tested quickly. Do not use that cap for
publication runs unless the report clearly labels the context budget.

### Why two phases?

Consolidation is the expensive step — LLM reflection + embedding for every
moment across all instances. For LongMemEval (500 instances × ~500 turns),
this costs ~$250+ in API calls. The prepare phase runs this once and saves
the full memory state (SQLite DB + hot memory markdown files) per instance.

The bench phase loads saved state and only runs recall + answer generation.
When testing a new recall strategy (e.g., dumping all hot memory into context
instead of grepping), only re-run bench — zero consolidation cost.

### Resumption

Both phases support `--resume` for crash recovery:

```bash
# Resume a prepare run that was interrupted
python -m benchmarks.academic prepare \
    --benchmark longmemeval --system alive --workers 16 --resume

# Resume a bench run
python -m benchmarks.academic bench \
    --benchmark longmemeval \
    --prepared-dir benchmarks/academic/prepared/longmemeval/alive \
    --workers 16 --resume
```

### Saved state per instance

```
prepared/longmemeval/alive/
  progress.json           # tracks which instances are done
  instance_000/
    bench.db              # SQLite (cold_memory, totems, traits, etc.)
    memory/               # hot memory markdown (journal, visitors, etc.)
    meta.json             # instance metadata, queries, ground truth,
                          #   hot_memory_tokens, cold_count, timings
  instance_001/
  ...
```

### One-shot run (legacy)

The original single-pass runner is still available:

```bash
python -m benchmarks.academic run --benchmark longmemeval --systems alive
python -m benchmarks.academic.parallel_run --benchmark longmemeval --system alive --workers 16
```

These do ingest + consolidate + query in one pass and discard intermediate
state. Use the two-phase workflow instead for iterative development.

## Systems Under Test

| ID | System | What It Does |
|----|--------|-------------|
| `lcb` | LangChain ConversationBufferMemory | Last N messages in a list |
| `lcs` | LangChain ConversationSummaryMemory | LLM summarizes into running summary |
| `mem0` | Mem0 | Graph-based entity/fact extraction |
| `zep` | Zep | Summaries + fact extraction |
| `rag` | ChromaDB + top-k | Vector similarity baseline |
| `rag+` | ChromaDB + LLM maintenance | RAG with same LLM budget as alive |
| `alive` | alive-memory | Autobiographical, identity-preserving, emotionally weighted memory |

## Autobiographical Track

Future benchmark work must include an owned persistent-agent eval alongside
LoCoMo, LongMemEval, MemoryAgentBench, and MemoryArena. This track should test:

- Stable agent identity across sessions, sleep cycles, and process restart
- Current visitor tastes after reinforcement, correction, and contradiction
- Emotionally weighted recall for autobiographical queries without emotional pollution
- Person-boundary protection across multiple visitors with conflicting tastes
- Evidence-grounded narratives where every identity or taste claim traces to source events
- Change legibility: what changed, when it changed, and why old beliefs are superseded

Required adapter metadata for this track:

- `agent_id`, `visitor_id`, `session_id`, `turn_index`, and `timestamp`
- `identity_scope`: `self`, `visitor`, `relationship`, or `world`
- affect fields: `valence`, `arousal`, and optional label
- `evidence_ids` on retrieved memories and generated narrative claims

Do not report alive-memory as better for persistent agents unless it wins this
track against generic RAG, summary memory, profile/fact memory, and comparable
SOTA systems under matched model, token, latency, and storage budgets.

Current harness support: `autobiographical_agent_3k` queries carry
`autobiographical_axes`, benchmark result JSON includes
`autobiographical_summary` and per-query `autobiographical_scores`, and reports
include an Autobiographical Memory scorecard. Result JSON also includes a
`run_manifest` with dataset hashes and `recall_traces` with retrieved snippets,
scores, timestamps, tiers, and evidence ids where adapters provide them.

## Before Full Runs

Run this checklist before starting a long or expensive benchmark:

- Audit the Track E evaluator. `autobiographical_agent_3k` now scores identity
  consistency, current tastes, emotional salience, preference updates,
  contradiction handling, abstention, temporal specificity, boundary integrity,
  and evidence grounding separately from generic F1, but the cases still need
  human review before publication-grade claims.
- Decide the competitor set in advance. Include alive-memory, no-memory,
  full-context/oracle where applicable, summary memory, vector RAG, Mem0,
  Zep/Graphiti, Mastra Observational Memory or an observation-log equivalent,
  and MemGPT/Letta-style memory where adapters are available.
- Extend the generated manifest with model names, prompts, adapter versions,
  hardware, context budgets, token budgets, latency budgets, and storage
  budgets. The harness already records dataset paths, counts, hashes, seeds,
  and git SHA.
- MemoryArena is prepared for alive-memory. Decide the MemoryAgentBench context
  budget before making claims that depend on that track. If a track is skipped
  or capped, state that explicitly in the report.
- Confirm evidence traces are complete for every adapter. The runner already
  saves retrieved snippets, scores, timestamps, tiers, and evidence ids where
  adapters provide them; missing adapter metadata should be treated as a gap.
- Smoke-test every configured system with a short run before a full run.
- Track ingest latency, recall latency, consolidation latency, answer latency,
  tokens, estimated cost, stored-memory count, and disk size.
- Spot-check synthetic ground truth, especially current vs. superseded
  preference and emotionally important vs. merely repeated memories.

## Adding a New System

Implement `MemoryAdapter` (4 required methods):

```python
from benchmarks.adapters.base import MemoryAdapter, BenchEvent, RecallResult, SystemStats

class MyAdapter(MemoryAdapter):
    async def setup(self, config: dict) -> None: ...
    async def ingest(self, event: BenchEvent) -> None: ...
    async def recall(self, query: str, limit: int = 5) -> list[RecallResult]: ...
    async def get_stats(self) -> SystemStats: ...
```

Register in `benchmarks/__main__.py` `ADAPTER_REGISTRY`.

## Methodology

See `docs/BENCHMARK_SPEC.md` and `docs/eval-suite-spec.md` for full design
rationale and the required autobiographical metrics.
