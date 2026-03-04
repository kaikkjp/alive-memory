# alive-memory Benchmark Report

Generated from results in `benchmarks/results`

All values: mean ± 95% CI from multiple seeds.
No OVERALL row — readers draw their own conclusions.

## Stream: research_assistant_10k

### Summary Table

| Metric | alive | lcb | rag | rag+ |
|--------|--------|--------|--------|--------|
| Recall F1 | 0.374 | 0.420 | 0.464 | 0.464 |
| Contradiction | 0.000 | 0.000 | 0.000 | 0.000 |
| Cost ($) | $0.00 | $0.00 | $0.00 | $0.00 |
| Storage | 3.3 MB | 114 KB | 136.4 MB | 7.6 MB |
| Memories | 1,000 | 941 | 1,000 | 574 |

### Recall by Category

| Category | alive | lcb | rag | rag+ |
|----------|--------|--------|--------|--------|
| basic_recall | 0.286 | 0.615 | 0.667 | 0.667 |
| entity_tracking | 0.250 | 0.250 | 0.125 | 0.125 |
| multi_hop | 0.500 | 0.250 | 0.000 | 0.000 |
| needle_in_haystack | 0.000 | 0.000 | 0.333 | 0.333 |
| negative_recall | 1.000 | 1.000 | 1.000 | 1.000 |
| topic_recall | 0.333 | 0.571 | 1.000 | 1.000 |

### Ranking Quality

| Metric | alive | lcb | rag | rag+ |
|--------|--------|--------|--------|--------|
| MRR | 0.536 | 0.429 | 0.457 | 0.476 |
| MRR (basic_recall) | 0.500 | 1.000 | 1.000 | 1.000 |
| MRR (entity_tracking) | 0.625 | 0.250 | 0.100 | 0.167 |
| MRR (multi_hop) | 1.000 | 0.500 | 0.000 | 0.000 |
| MRR (needle_in_haystack) | 0.000 | 0.000 | 1.000 | 1.000 |
| MRR (negative_recall) | 0.000 | 0.000 | 0.000 | 0.000 |
| MRR (topic_recall) | 1.000 | 1.000 | 1.000 | 1.000 |

### Reliability

| Metric | alive | lcb | rag | rag+ |
|--------|--------|--------|--------|--------|
| Fabrication rate | 0.000 | 0.000 | 0.000 | 0.000 |
| Entity confusion rate | 1.000 | 1.000 | 0.000 | 0.000 |

### Scale Degradation

| Cycle | alive | lcb | rag | rag+ |
|-------|--------|--------|--------|--------|
| 100 | 0.200 | 0.423 | 0.696 | 0.673 |
| 500 | 0.327 | 0.327 | 0.476 | 0.476 |
| 1,000 | 0.374 | 0.420 | 0.464 | 0.464 |

### Resource Efficiency

| Metric | alive | lcb | rag | rag+ |
|--------|--------|--------|--------|--------|
| Wall time (s) | 2.6s | 0.0s | 12.4s | 6.9s |
| LLM calls | 0 | 0 | 0 | 0 |
| Tokens | 0 | 0 | 0 | 0 |
| Avg ingest latency | 2.6ms | 0.0ms | 12.1ms | 6.7ms |
| Avg recall latency | 0.8ms | 0.0ms | 11.0ms | 8.4ms |
| Avg consolidate latency | 2.9ms | 0.0ms | 0.0ms | 0.0ms |

### Efficiency

| Metric | alive | lcb | rag | rag+ |
|--------|--------|--------|--------|--------|
| F1 improvement | +0.174 | -0.004 | -0.232 | -0.209 |
| Quality retention | 1.87x | 0.99x | 0.67x | 0.69x |
| p999 recall latency | 3.4ms | 0.0ms | 31.4ms | 10.9ms |

### alive-memory Specific

**Salience & Consolidation:**

- **alive**: 83 events with salience data, 0 dreams, 0 reflections, 2 consolidation reports

**Memory Tier Distribution:**

- **alive**: hot: 100%
- **lcb**: unknown: 100%
- **rag**: unknown: 100%
- **rag+**: unknown: 100%


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