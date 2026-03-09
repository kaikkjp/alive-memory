# Benchmark Specification for alive-memory

## 1. Objective

Build a reproducible benchmark harness that compares alive-memory against
standard baselines and memory-architecture baselines across four evaluation
tracks: very long-term conversation, chat-assistant memory, incremental agent
memory, and interdependent multi-session agent memory. The selected tracks are
grounded in LoCoMo, LongMemEval, MemoryAgentBench, and MemoryArena.

## 2. Evaluation Tracks

### Track A — Conversational memory: LoCoMo

Evaluate on:
- Question answering
- Event summarization
- Multimodal dialogue generation

LoCoMo is built around very long multi-session conversations and explicitly
includes those three tasks. The paper also reports a human QA row, so a human
upper-bound is available for the QA track.

### Track B — Chat-assistant memory: LongMemEval

Evaluate on:
- Information extraction
- Multi-session reasoning
- Temporal reasoning
- Knowledge updates
- Abstention

LongMemEval defines those five abilities. It also includes an oracle setting
in the paper/repo, which should be reported separately from standard runs
rather than treated as a generic "human upper-bound."

### Track C — Incremental agent memory: MemoryAgentBench

Evaluate on:
- Accurate Retrieval (AR)
- Test-Time Learning (TTL)
- Long-Range Understanding (LRU)
- Conflict Resolution (CR)

MemoryAgentBench is explicitly designed around incremental multi-turn
interactions and names those four competencies.

### Track D — Multi-session agent memory: MemoryArena

Evaluate on:
- Web navigation
- Preference-constrained planning
- Progressive information search
- Sequential formal reasoning

MemoryArena defines those agentic task families and is positioned specifically
as a benchmark for interdependent multi-session agentic tasks.

## 3. Systems to Benchmark

### Mandatory baselines

| # | System | Description |
|---|--------|-------------|
| 1 | No external memory | Model uses only the current prompt |
| 2 | Full-context | Provide the entire available history to the model |
| 3 | Summary-memory | Rolling summary only |
| 4 | Vanilla RAG | Dense retrieval over stored history chunks |

### Memory-architecture baselines

| # | System | Description |
|---|--------|-------------|
| 5 | MemGPT | Hierarchical/tiered memory management for extended context beyond the model's context window |
| 6 | Mem0 | Scalable long-term memory with extraction, consolidation, and retrieval |
| 7 | A-MEM | Dynamic agentic memory with indexing, linking, and memory evolution. Track support counted only where adapter is validated |
| 8 | Target system (alive-memory) | Three-tier cognitive memory |

## 4. Benchmark Matrix

| System | LoCoMo | LongMemEval | MemoryAgentBench | MemoryArena |
|--------|--------|-------------|------------------|-------------|
| No external memory | Yes | Yes | Yes | Yes |
| Full-context | Yes | Yes | Yes | Yes |
| Summary-memory | Yes | Yes | Yes | Yes |
| Vanilla RAG | Yes | Yes | Yes | Yes |
| MemGPT | Yes | Yes | Yes | Yes |
| Mem0 | Yes | Yes | Yes | Yes |
| A-MEM | Only if adapter validated | Only if adapter validated | Only if adapter validated | Only if adapter validated |
| **alive-memory** | **Yes** | **Yes** | **Yes** | **Yes** |
| Human upper-bound | LoCoMo QA only | No | No | No |
| Oracle condition | No | Yes, report separately | No | No |

LoCoMo publishes a human QA result. LongMemEval publishes oracle-condition
results; that condition should be reported separately, not mixed into the main
baseline table.

## 5. Primary Metrics

### Benchmark-native metrics

Use each benchmark's official task metrics and evaluation scripts first.

- **LoCoMo**: Answer prediction metrics for QA, task-specific metrics for
  summarization/dialogue generation
- **LongMemEval**: Benchmark score/accuracy with released evaluation flow;
  uses LLM evaluator with strong human agreement
- **MemoryAgentBench**: Benchmark-native evaluation over AR, TTL, LRU, CR
- **MemoryArena**: Task-family benchmark performance by environment/task type

### Harness-level systems metrics

Add these to every run:

| Metric | Description |
|--------|-------------|
| Median latency | Per-query response time |
| p95 latency | Tail latency |
| Token cost per query/episode | Tokens consumed by memory operations |
| Memory storage size | Final memory footprint |
| Retrieval hit rate | Fraction of answer-supporting memories retrieved |
| Abstention correctness | Correct "I don't know" rate (where applicable) |
| Relative gain vs. vanilla RAG | Delta over the RAG baseline |
| Scalability curve | Score vs. session count / history size |
| Memory-update latency | Consolidation, re-indexing, pruning time |
| Contradiction/conflict rate | Where supported by benchmark |

These are harness-defined engineering metrics, not benchmark-native metrics.

## 6. Experimental Controls

Hold constant across all systems:

- Same base LLM
- Same context window assumption
- Same embedding model for all retrieval-based systems
- Same chunking family, with parameter values reported
- Same retrieval budget
- Same generation prompt template where possible
- Same hardware / serving setup
- Same seeds and run counts
- Same dataset versions and evaluation scripts

For evaluation:
- Use each benchmark's native evaluation protocol
- Where a benchmark's released scripts use an LLM judge, lock the judge model,
  prompt, and temperature

LongMemEval uses gpt-4o-2024-08-06 as evaluator. MemoryAgentBench's repo
includes LLM-based evaluation scripts.

## 7. Standardized Memory System API

Every system implements the same thin interface so baselines can be swapped
with config changes only.

```python
class MemorySystem:
    def reset(self, run_id: str) -> None: ...
    def ingest(self, event: dict) -> None: ...
    def retrieve(self, query: str, k: int = 10) -> list[dict]: ...
    def update(self) -> dict: ...
    def stats(self) -> dict: ...
```

### Required event schema

```json
{
  "timestamp": "ISO-8601",
  "session_id": "string",
  "speaker": "user|assistant|system|env",
  "content": "string",
  "metadata": {}
}
```

### Required retrieval record schema

```json
{
  "memory_id": "string",
  "text": "string",
  "score": 0.0,
  "timestamp": "ISO-8601",
  "source_session_id": "string",
  "metadata": {}
}
```

## 8. Execution Plan

### Phase 1 — Core runs

**Systems**: No external memory, Full-context, Summary-memory, Vanilla RAG,
alive-memory

**Benchmarks**: LoCoMo, LongMemEval, MemoryAgentBench

### Phase 2 — Memory-architecture runs

**Add**: MemGPT, Mem0, A-MEM (where adapter is validated)

**Benchmarks**: LoCoMo, LongMemEval, MemoryAgentBench, MemoryArena

### Phase 3 — Efficiency and scaling

For every system/track combination, report:
- Primary benchmark score
- Subtask scores
- Median latency, p95 latency
- Token cost
- Storage footprint
- Scaling plots vs. session count / history size

MemoryArena is reserved for Phase 2 because it exposes weaknesses not visible
on long-context memory benchmarks alone.

## 9. Required Output Tables

1. **Overall score by benchmark**
2. **Subtask score by benchmark**
   - LoCoMo: QA / event summarization / dialogue generation
   - LongMemEval: extraction / multi-session reasoning / temporal reasoning /
     knowledge updates / abstention
   - MemoryAgentBench: AR / TTL / LRU / CR
   - MemoryArena: web navigation / preference planning / progressive search /
     sequential reasoning
3. **Efficiency table** — median latency, p95 latency, token cost, storage
4. **Retrieval-quality table** — hit rate, abstention correctness,
   contradiction/conflict rate
5. **Scalability table/plots** — score vs. session count or history tokens
6. **Ablation table** for alive-memory, at minimum:
   - Retrieval on/off
   - Consolidation on/off
   - Pruning on/off
   - Temporal-aware retrieval on/off
   - Graph/linking on/off (if applicable)

## 10. Program Success Criteria

These are project-defined success criteria, not benchmark-defined standards.
Use this pre-registered template:

- Target beats No external memory, Full-context, Summary-memory, and Vanilla
  RAG by pre-registered deltas on selected primary scores
- Target matches or beats at least one of MemGPT, Mem0, or A-MEM on at least
  two tracks
- Target token cost is no worse than Full-context
- Target scaling degradation stays below the pre-registered ceiling under
  larger histories / more sessions

**If you want numeric gates, lock them before running. Do not set them after
seeing results.**

## 11. Deliverables

- [ ] Dockerized benchmark harness
- [ ] Adapters for LoCoMo, LongMemEval, MemoryAgentBench, MemoryArena
- [ ] Baseline wrappers implementing the common Memory System API
- [ ] Config files for every system
- [ ] Dataset version manifest
- [ ] Exact seeds
- [ ] Run scripts
- [ ] Final report with:
  - Benchmark-level results
  - Subtask results
  - Scaling plots
  - Efficiency metrics
  - Ablations
  - Failure analysis

## 12. Resources

### Benchmarks
- LoCoMo: [paper](https://arxiv.org/abs/2402.17753) and repo
- LongMemEval: [paper](https://arxiv.org/abs/2407.15460), site, and repo
- MemoryAgentBench: [paper](https://arxiv.org/abs/2501.14200) and repo
- MemoryArena: paper (states release at project site)

### Memory baselines
- MemGPT: [paper](https://arxiv.org/abs/2310.08560)
- Mem0: paper and [repo](https://github.com/mem0ai/mem0)
- A-MEM: paper and repos

## 13. Minimal Version

**Systems**: Full-context, Summary-memory, Vanilla RAG, MemGPT, alive-memory

**Benchmarks**: LoCoMo, LongMemEval, MemoryAgentBench

This keeps the harness manageable while covering conversation memory, assistant
memory, and incremental agent memory.
