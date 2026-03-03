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
