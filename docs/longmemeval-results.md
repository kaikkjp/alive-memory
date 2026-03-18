# LongMemEval Benchmark Results — alive-memory

**Date**: 2026-03-19
**Branch**: `claude/fix-tier-roles`
**Dataset**: LongMemEval-S (500 questions, ~115k tokens/question, ~40 sessions)
**Paper**: https://arxiv.org/abs/2410.10813

## alive-memory Configuration

- **System**: alive (three-tier cognitive memory)
- **LLM (consolidation)**: gpt-4o-mini (OpenAI)
- **LLM (answer generation)**: gpt-4o-mini (OpenAI)
- **Embedder**: text-embedding-3-small (OpenAI)
- **Consolidation depth**: full (every moment reflected)
- **Salience threshold**: 0.0 (everything ingested)
- **Workers**: 16 (ProcessPoolExecutor)
- **Wall time**: 137,020s (~38 hours)
- **LLM calls (answer gen)**: 8,095
- **Tokens (answer gen)**: 8.3M
- **Estimated total cost**: ~$106 (mostly consolidation reflections)

## Results

### Aggregate

| Metric | Score |
|---|---|
| Accuracy | 37.4% |
| Exact Match | 0.6% |
| F1 | 16.3% |
| Substring Hit | 32.8% |

### Per-Category Breakdown

| Category | Accuracy | F1 | Substring Hit |
|---|---|---|---|
| Information Extraction | 64.0% | 29.1% | 54.0% |
| Knowledge Updates | 51.4% | 19.0% | 45.8% |
| Multi-Session Reasoning | 27.3% | 6.8% | 26.4% |
| Temporal Reasoning | 15.7% | 11.0% | 14.2% |
| Abstention | 3.3% | 6.1% | 0.0% |

## Comparison with Other Systems

| System | Overall Accuracy | Info Extract | Multi-Session | Temporal | Knowledge Update |
|---|---|---|---|---|---|
| Mastra OM (gpt-5-mini) | **94.9%** | ~96% | 87.2% | 95.5% | 96.2% |
| EmergenceMem Internal | 86.0% | ~99% | 81.2% | 85.7% | 83.3% |
| Oracle GPT-4o | 82.4% | — | — | — | — |
| Accumulator | 81.8% | — | — | — | — |
| Full Context GPT o3 | 76.0% | — | — | — | — |
| Zep | 71.2% | ~87% | 57.9% | 62.4% | 83.3% |
| Full Context GPT-4o | 63.8% | — | — | — | — |
| **alive-memory** | **37.4%** | **64.0%** | **27.3%** | **15.7%** | **51.4%** |

Sources:
- [Emergence AI — SOTA on LongMemEval with RAG](https://www.emergence.ai/blog/sota-on-longmemeval-with-rag)
- [Mastra — Observational Memory: 95% on LongMemEval](https://mastra.ai/research/observational-memory)

## Analysis: Why alive-memory Underperforms

### 1. Lossy Consolidation

alive-memory's three-tier architecture (day → hot → cold) consolidates raw conversation turns into journal reflections, totems, and traits. This **loses raw detail** — exact names, numbers, dates, preferences — that LongMemEval questions specifically ask about. Top systems (Mastra OM, EmergenceMem) use direct RAG over raw conversation turns, preserving every detail.

### 2. Temporal Reasoning (15.7% vs 85%+)

The worst category. alive-memory stores timestamps in moment metadata but doesn't surface temporal relationships during recall. Questions like "What did I say BEFORE/AFTER X?" or "When did I first mention Y?" require temporal indexing that the current recall system doesn't support.

### 3. Multi-Session Reasoning (27.3% vs 80%+)

Questions requiring synthesis across multiple sessions. alive-memory's recall is keyword-based grep over hot memory markdown files — it struggles to find and connect information scattered across sessions. Vector search over cold embeddings helps but the embeddings are of consolidated reflections, not raw turns.

### 4. Abstention (3.3%)

alive-memory almost never says "I don't know." It generates answers even when it has no relevant memory, producing hallucinated responses. Needs a confidence threshold or explicit abstention logic.

### 5. Reflection Truncation (fixed this run)

Previously `moment.content[:800]` — only 800 chars of each moment were sent to the reflection LLM. Fixed to send full content. Cold embedding also previously failed on moments >8192 tokens — fixed with 7000 char truncation.

### 6. Cost vs Quality Tradeoff

Every moment gets a full LLM reflection call (gpt-4o-mini). At ~190k moments across 500 instances, this cost ~$85+ in consolidation alone. The top systems spend their LLM budget on answer generation with full context, not on summarization that loses information.

## Recommendations for Next Iteration

### High Impact
1. **Add raw turn storage to cold tier** — Store full conversation turns alongside consolidated reflections. Use RAG over raw turns for recall, not just reflections.
2. **Temporal indexing** — Index moments by timestamp and support temporal queries (before/after/first/last).
3. **Abstention detection** — When recall returns low-relevance results, output "I don't know" instead of guessing.

### Medium Impact
4. **Hybrid recall** — Combine keyword grep (hot) + vector search (cold) + raw turn search in a single recall pass.
5. **Selective reflection** — Don't reflect on every moment. Use salience to skip low-value turns (greetings, acknowledgments). Saves cost and reduces noise.
6. **Better fact extraction** — Extract more structured facts (dates, quantities, preferences) into totems with explicit temporal metadata.

### Low Impact (Quality of Life)
7. **Sanitize control characters** — Strip `\x00`-`\x1F` from content before sending to OpenAI API to avoid JSON parse errors.
8. **Work queue for parallel runner** — Use `asyncio.Queue` instead of static chunking so fast workers can pick up more instances.

## Raw Results

Full results JSON: `benchmarks/academic/results/longmemeval/alive.json`
