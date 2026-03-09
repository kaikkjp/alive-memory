# Alive-Memory Academic Benchmark Specification

## 1. Objective

Establish a benchmark suite for alive-memory that measures performance against
standard non-memory baselines, retrieval baselines, and memory-architecture
baselines across conversational, assistant, and agentic settings using
published academic benchmarks.

## 2. Evaluation Scope — Four Tracks

| Track | Benchmark | Setting | What it evaluates |
|-------|-----------|---------|-------------------|
| **A** | [LoCoMo](https://arxiv.org/abs/2402.17753) | Conversational | QA, event summarization, dialogue generation over very long conversations |
| **B** | [LongMemEval](https://arxiv.org/abs/2407.15460) | Chat assistant | Information extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention |
| **C** | [MemoryAgentBench](https://arxiv.org/abs/2501.14200) | Incremental agent | Retrieval, test-time learning, long-range understanding, selective forgetting |
| **D** | [MemoryArena](https://arxiv.org/abs/2504.12345) | Multi-session agent | Memory inside multi-session agent-environment loops with interdependent subtasks |

## 3. Systems Under Test

### Mandatory baselines (Phase 1)

| ID | System | Description |
|----|--------|-------------|
| `no-memory` | No external memory | Model uses only the current prompt, no history |
| `full-context` | Full context window | Entire conversation history passed as context |
| `summary` | Rolling summary | LLM-maintained running summary of history |
| `rag` | Vanilla RAG | Dense retrieval (embedding similarity) over stored chunks |
| `alive` | alive-memory | Three-tier cognitive memory (target system) |

### Memory-architecture baselines (Phase 2)

| ID | System | Description |
|----|--------|-------------|
| `memgpt` | [MemGPT/Letta](https://arxiv.org/abs/2310.08560) | Hierarchical/tiered memory with LLM-managed paging |
| `mem0` | [Mem0](https://github.com/mem0ai/mem0) | Graph-based entity/fact extraction |
| `a-mem` | [A-MEM](https://arxiv.org/abs/2502.12345) | Agentic memory with dynamic organization and linking |

## 4. Benchmark Matrix

| System | LoCoMo | LongMemEval | MemoryAgentBench | MemoryArena |
|--------|--------|-------------|------------------|-------------|
| no-memory | Phase 1 | Phase 1 | Phase 1 | — |
| full-context | Phase 1 | Phase 1 | Phase 1 | — |
| summary | Phase 1 | Phase 1 | Phase 1 | — |
| rag | Phase 1 | Phase 1 | Phase 1 | — |
| **alive** | **Phase 1** | **Phase 1** | **Phase 1** | **Phase 2** |
| memgpt | Phase 2 | Phase 2 | Phase 2 | Phase 2 |
| mem0 | Phase 2 | Phase 2 | Phase 2 | Phase 2 |
| a-mem | Optional | Phase 2 | Phase 2 | Phase 2 |

## 5. Primary Metrics

### Task metrics (benchmark-native)

Each benchmark defines its own evaluation tasks and scoring. Use the official
metrics as-is:

- **LoCoMo**: F1, BLEU, ROUGE-L for QA; BERTScore for summarization/dialogue
- **LongMemEval**: Accuracy per ability (extraction, reasoning, temporal, updates, abstention)
- **MemoryAgentBench**: Task completion rate, accuracy by category
- **MemoryArena**: Subtask success rate, cross-session dependency resolution

### Systems metrics (common layer)

| Metric | Unit | Description |
|--------|------|-------------|
| Latency (median) | ms | Per-query response time |
| Latency (p95) | ms | Tail latency |
| Token cost | tokens | Total tokens consumed by memory operations |
| LLM calls | count | Number of LLM API calls for memory management |
| Storage | bytes | Final memory footprint |
| Retrieval hit rate | ratio | Fraction of answer-supporting memories retrieved |
| Abstention correctness | ratio | Correct "I don't know" rate (LongMemEval) |
| Cost-normalized score | score/$ | Task score per dollar of LLM cost |

### Scale degradation (alive-specific)

Plot task score vs. history length at checkpoints (100, 1k, 5k, 10k, 50k
events) to demonstrate graceful degradation.

## 6. Standardized Experimental Controls

Hold constant across **all** systems in a single run:

| Control | Rationale |
|---------|-----------|
| Base LLM (e.g., Claude Haiku 4.5) | Isolate memory architecture from model capability |
| Tokenizer / context limit | Fair comparison of what fits in context |
| Embedding model (e.g., all-MiniLM-L6-v2) | Fair retrieval comparison |
| Chunking policy (size, overlap) | Consistent input segmentation |
| Answer generation prompt template | Same reasoning prompt for all systems |
| Max retrieval budget per query (k=5) | Same retrieval window |
| Hardware / serving config | Same latency baseline |
| Random seeds (42, 123, 456) | Reproducibility |

## 7. Execution Plan

### Phase 1 — Core benchmark

**Systems**: no-memory, full-context, summary, rag, alive

**Benchmarks**: LoCoMo, LongMemEval, MemoryAgentBench

**Goal**: Establish alive's position against fundamental baselines.

### Phase 2 — Architecture benchmark

**Add systems**: memgpt, mem0, a-mem

**Benchmarks**: LongMemEval, MemoryAgentBench, MemoryArena

**Goal**: Head-to-head against memory-specialized architectures.

### Phase 3 — Efficiency benchmark

For every system, report: benchmark score, median latency, p95 latency,
token usage, storage footprint, cost-normalized score.

## 8. Required Result Tables

### 8.1 Overall score by benchmark

| System | LoCoMo | LongMemEval | MemoryAgentBench | MemoryArena |
|--------|--------|-------------|------------------|-------------|
| ... | ... | ... | ... | ... |

### 8.2 Per-subtask breakdown

**LoCoMo**: QA / event summarization / dialogue generation

**LongMemEval**: extraction / multi-session reasoning / temporal reasoning /
knowledge updates / abstention

**MemoryAgentBench**: retrieval / test-time learning / long-range understanding /
selective forgetting

**MemoryArena**: task-family breakdown

### 8.3 Efficiency table

| System | Score | Latency (med) | Latency (p95) | Tokens | LLM Calls | Storage | Score/$ |
|--------|-------|---------------|---------------|--------|-----------|---------|---------|
| ... | ... | ... | ... | ... | ... | ... | ... |

### 8.4 Ablation table (alive-memory only)

| Ablation | LoCoMo | LongMemEval | MemoryAgentBench |
|----------|--------|-------------|------------------|
| Full system | — | — | — |
| - consolidation | — | — | — |
| - cold archive | — | — | — |
| - salience gating | — | — | — |
| - dreaming | — | — | — |
| - identity/self-model | — | — | — |
| - temporal reasoning | — | — | — |

## 9. Success Criteria

1. alive **exceeds** no-memory, full-context, summary, and rag on the primary
   score of each benchmark at scale (10k+ events).
2. alive **matches or exceeds** at least one of MemGPT, Mem0, A-MEM on at
   least two benchmark tracks.
3. alive reports **lower or comparable token cost** than full-context.
4. alive maintains performance under **multi-session and incremental** settings
   (LongMemEval, MemoryAgentBench, MemoryArena).
5. alive demonstrates **graceful scale degradation** — less than 20% score
   drop from 1k to 10k events.

## 10. Deliverables

- [ ] Benchmark harness (`benchmarks/academic/`)
- [ ] Dataset adapters for LoCoMo, LongMemEval, MemoryAgentBench, MemoryArena
- [ ] System adapters for all baseline and comparison systems
- [ ] Config files for each system
- [ ] Reproducibility manifest (seeds, versions, hardware)
- [ ] Final report with overall scores, subtask scores, efficiency, ablations,
      error analysis

## 11. Minimal Version (Phase 1 only)

**Systems**: full-context, summary, rag, memgpt, alive

**Benchmarks**: LoCoMo, LongMemEval, MemoryAgentBench

This is the smallest credible benchmark that demonstrates alive-memory's
position against both baselines and at least one memory architecture.
