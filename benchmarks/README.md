# alive-memory Benchmark Framework

Longitudinal benchmarks comparing agent memory systems over thousands of cycles.

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
| `alive` | alive-memory | Three-tier cognitive memory |

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

See `docs/alive-memory-benchmark-plan.md` for full design rationale.
