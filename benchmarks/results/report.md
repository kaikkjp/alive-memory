# alive-memory Benchmark Report

Generated from results in `benchmarks/results`

All values: mean ± 95% CI from multiple seeds.
No OVERALL row — readers draw their own conclusions.

## Stream: research_assistant_10k

### Summary Table

| Metric | alive | rag |
|--------|--------|--------|
| Recall F1 | 0.338 | 0.173 |
| Contradiction | 0.000 | 0.000 |
| Cost ($) | $0.01 | $0.00 |
| Storage | 3.3 MB | 241742.9 MB |
| Memories | 1,000 | 10,000 |

### Recall by Category

| Category | alive | rag |
|----------|--------|--------|
| basic_recall | 0.286 | 0.667 |
| entity_tracking | 0.250 | 0.000 |
| fact_update | 0.000 | 0.067 |
| multi_hop | 0.250 | 0.000 |
| needle_in_haystack | 0.000 | 0.067 |
| negative_recall | 1.000 | 1.000 |
| temporal_distance | 0.000 | 0.667 |
| topic_recall | 0.333 | 1.000 |

### Ranking Quality

| Metric | alive | rag |
|--------|--------|--------|
| MRR | 0.536 | 0.222 |
| MRR (basic_recall) | 0.500 | 1.000 |
| MRR (entity_tracking) | 0.625 | 0.000 |
| MRR (fact_update) | 0.000 | 0.133 |
| MRR (multi_hop) | 1.000 | 0.000 |
| MRR (needle_in_haystack) | 0.000 | 0.200 |
| MRR (negative_recall) | 0.000 | 0.000 |
| MRR (temporal_distance) | 0.000 | 1.000 |
| MRR (topic_recall) | 1.000 | 1.000 |

### Reliability

| Metric | alive | rag |
|--------|--------|--------|
| Fabrication rate | 1.000 | 0.000 |
| Entity confusion rate | 1.000 | 0.000 |

### Scale Degradation

| Cycle | alive | rag |
|-------|--------|--------|
| 100 | 0.200 | 0.673 |
| 500 | 0.184 | 0.625 |
| 1,000 | 0.338 | 0.496 |
| 2,000 | 0.000 | 0.333 |
| 5,000 | 0.000 | 0.235 |
| 10,000 | 0.000 | 0.173 |

### Resource Efficiency

| Metric | alive | rag |
|--------|--------|--------|
| Wall time (s) | 28.5s | 109.3s |
| LLM calls | 10 | 0 |
| Tokens | 3,147 | 0 |
| Avg ingest latency | 2.6ms | 10.8ms |
| Avg recall latency | 1.6ms | 10.5ms |
| Avg consolidate latency | 12915.3ms | 0.0ms |

### Efficiency

| Metric | alive | rag |
|--------|--------|--------|
| F1 improvement | +0.138 | -0.500 |
| Quality retention | 1.69x | 0.26x |
| p999 recall latency | 3.9ms | 29.5ms |

### alive-memory Specific

**Salience & Consolidation:**

- **alive**: 83 events with salience data, 0 dreams, 10 reflections, 2 consolidation reports

**Memory Tier Distribution:**

- **alive**: hot: 100%


## Methodology

- Each system uses its recommended best-practice configuration
- RAG+ variant gets the same LLM budget as alive for periodic maintenance
- Hard ground truth: deterministic substring matching
- Soft ground truth (pattern_recognition, emotional_context): 3 LLM judges, majority vote
- Identity consistency reported separately (only alive-memory supports it)
- All competitor versions pinned in requirements.txt

## Reproduction

```bash
# Generate data
python -m benchmarks generate --scenario research_assistant

# Run all systems with 5 seeds
python -m benchmarks run --stream research_assistant_10k --all --seeds 42,123,456,789,1337

# Generate this report
python -m benchmarks report --results-dir benchmarks/results/
```