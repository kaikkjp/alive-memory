# Plan: Implement 11 Missing Benchmark Metrics

## Context

The alive-sdk benchmark framework compares alive-memory against 6 competitor memory systems across recall quality, contradiction handling, scale, noise resilience, identity, and cost. There are 11 gaps in the metric coverage that would strengthen the case for alive-memory's superiority. This plan adds all 11 metrics.

## Shared Infrastructure (do first)

These 4 changes underpin multiple metrics and must be done before the metric modules.

### S1. Add `relevance_vector` to `ScoredRecall` (`benchmarks/scoring/hard_truth.py`)
- Add `relevance_vector: list[bool] = field(default_factory=list)` to the dataclass
- Populate it in `score_recall()` from the existing `relevant_flags` local variable (1 line: `relevance_vector=relevant_flags`)
- Used by: NDCG metric

### S2. Add `get_adapter_data()` to `MemoryAdapter` (`benchmarks/adapters/base.py`)
- New optional method: `async def get_adapter_data(self) -> dict:` returning `{}`
- Used by: salience calibration, cold contribution, dream evaluation

### S3. Extend `CycleMetrics` and `BenchmarkResult.to_dict()` (`benchmarks/runner.py`)
- Add to `CycleMetrics`: `adapter_data: dict`, `traceability_results: list[dict]`, `entity_confusion_results: list[dict]`, `tier_distribution: dict` — all with `field(default_factory=...)`
- In `_measure()`: call `adapter.get_adapter_data()`, store in `metrics.adapter_data`; count recall results by `metadata.get("tier")` and store in `metrics.tier_distribution`
- In `to_dict()`: serialize new fields (skip if empty for backward compat)
- Add p999 to latency serialization in `to_dict()`

### S4. Extend alive adapter (`benchmarks/adapters/alive_adapter.py`)
- `ingest()`: capture `DayMoment` return from `intake()`, store `{cycle: salience}` mapping
- `recall()`: add `reflections` and `cold_echoes` from `RecallContext`; tag all results with `metadata["tier"]` = `"hot"` or `"cold"`
- `consolidate()`: capture `SleepReport`, accumulate dreams/reflections
- `get_adapter_data()`: return `{"salience_map": ..., "consolidation_reports": ..., "total_dreams": N, "total_reflections": N}`

---

## Metric Modules (8 new files in `benchmarks/metrics/`)

### M1. `ndcg.py` — Ranking Quality
```
NDCGResult: ndcg_at_5, ndcg_at_3, ndcg_by_category, mrr
compute_ndcg(result: BenchmarkResult) -> NDCGResult
```
- Reads `relevance_vector` from each `ScoredRecall` in `final_metrics.recall_scores`
- Formula: NDCG@k = DCG@k / IDCG@k, where DCG = sum(rel_i / log2(i+2))
- Binary relevance (0/1) based on existing `_is_relevant()` logic
- Groups by category for per-category NDCG

### M2. `hallucination.py` — Fabrication Rate
```
HallucinationResult: fabrication_rate, traceable_rate, fabrication_by_category, total_checked
compute_hallucination(result: BenchmarkResult) -> HallucinationResult
```
- Runner change: in `_measure()`, for each recall result, check traceability against event corpus
- Build content index at runner init: set of lowercased 4-word shingles from all events up to current cycle
- Result is "traceable" if >30% of its shingles are in the index
- Store per-query traceability in `CycleMetrics.traceability_results`
- Metric module reads from `final_metrics.traceability_results`

### M3. `consolidation_roi.py` — Cost-Effectiveness
```
ConsolidationROIResult: f1_per_dollar, f1_improvement, estimated_cost, marginal_curve, classification
compute_consolidation_roi(result: BenchmarkResult) -> ConsolidationROIResult
```
- Pure post-hoc from `metrics_over_time` (F1 values) and `final_stats` (total_tokens)
- `f1_improvement` = final F1 - first F1
- `estimated_cost` from token count using existing pricing constants
- `f1_per_dollar` = f1_improvement / max(estimated_cost, 0.001)
- Classification: "efficient" (>10 F1pts/$), "moderate" (1-10), "wasteful" (<1)

### M4. `entity_confusion.py` — Cross-Entity Contamination
```
EntityConfusionResult: confusion_rate, per_entity_confusion, most_confused_pairs
compute_entity_confusion(result: BenchmarkResult) -> EntityConfusionResult
```
- Runner change: add `score_entity_confusion()` to `hard_truth.py`
- During `_measure()`, for entity_tracking queries about user X, check if results mention other primary users' names
- Store in `CycleMetrics.entity_confusion_results`
- Metric module aggregates from `final_metrics.entity_confusion_results`

### M5. `salience_calibration.py` — Salience Predicts Retrieval (alive-only)
```
SalienceCalibrationResult: correlation, mean_salience_retrieved, mean_salience_missed, calibration_gap, supported
compute_salience_calibration(result: BenchmarkResult) -> SalienceCalibrationResult
```
- Reads `adapter_data["salience_map"]` from `final_metrics.adapter_data`
- Cross-references with recall success: events whose content appears in recall results are "retrieved"
- Pearson correlation between salience score and retrieval boolean
- Returns `supported=False` if `adapter_data` empty

### M6. `cold_contribution.py` — Cold vs Hot Memory (alive-only)
```
ColdContributionResult: cold_pct, hot_pct, reflection_pct, tier_distribution, supported
compute_cold_contribution(result: BenchmarkResult) -> ColdContributionResult
```
- Reads `tier_distribution` from each cycle in `metrics_over_time`
- Aggregates: percentage of results from each tier across all measurement points
- Returns `supported=False` if no tier data

### M7. `dream_evaluation.py` — Consolidation Output Quality (alive-only)
```
DreamEvaluationResult: coherence, relevance, dream_count, reflection_count, method, supported
compute_dream_evaluation(result: BenchmarkResult) -> DreamEvaluationResult
```
- Reads `adapter_data["consolidation_reports"]`
- Heuristic scoring (default, no LLM cost):
  - Length score (>20 words = 1.0, scales linearly)
  - Lexical diversity (unique_words / total_words)
  - Repetition penalty (detect repeated 3-grams)
- Returns `supported=False` if no consolidation data

### M8. `graceful_degradation.py` — Performance Under Pressure
```
GracefulDegradationResult: quality_retention, p999_ingest_ms, p999_recall_ms, p999_consolidate_ms, latency_growth_rate, quality_latency_tradeoff
compute_graceful_degradation(result: BenchmarkResult) -> GracefulDegradationResult
```
- `quality_retention` = F1 at last measurement / F1 at first measurement
- p999 from raw latency arrays (already in `result.latencies`)
- `latency_growth_rate` = linear regression of p95 latency at each measurement point vs log(cycle)
- Works with existing data; longer runs (stress_test 50K) provide better signal

---

## Runner Modes (3 new files)

### R1. `benchmarks/cross_domain.py` — Cross-Domain Transfer (Metric 9)
```
CrossDomainResult: transfer_f1, baseline_f1, transfer_ratio, interference_rate
```
- Phase 1: ingest events from scenario A (no queries)
- Phase 2: run queries from scenario B against populated memory
- New CLI subcommand: `python -m benchmarks cross-domain --train research_assistant --test customer_support`
- Requires customer_support scenario to have full queries/GT (extend `generate_streams.py`)

### R2. `benchmarks/concurrent_runner.py` — Concurrent Latency (Metric 11)
```
ConcurrentLatencyResult: throughput, p50/p95/p99/p999, error_rate, concurrency, degradation_ratio
```
- Uses `asyncio.gather` to run N parallel ingest+recall operations
- Measures throughput (ops/sec) and tail latency under contention
- New CLI subcommand: `python -m benchmarks stress --concurrency 10`

### R3. Selective Forgetting (Metric 10) — Runner + Generator Changes
- Add `async def forget(self, content_hint: str) -> bool` to `MemoryAdapter`
- Add `forget_verification` query category to `generate_streams.py`: after a planted needle, add a "forget" directive, then verify it's gone
- Add `score_forget_verification()` to `hard_truth.py`
- New metric module `benchmarks/metrics/selective_forgetting.py`:
  ```
  SelectiveForgettingResult: forget_success_rate, residual_recall_rate, supported
  ```

---

## Report Changes (`benchmarks/report.py`)

Add 4 new sections to `generate_markdown()`:
1. **Ranking Quality** — NDCG@5 table by system + by category
2. **Reliability** — Hallucination rate + entity confusion rate table
3. **Efficiency** — Consolidation ROI table + graceful degradation
4. **alive-memory Specific** — Salience calibration, cold contribution, dream evaluation (only shown if data present)

Add 2 new charts to `generate_charts()`:
1. **ROI Frontier** — F1 improvement vs cost scatter (like cost_quality but shows improvement delta)
2. **Hallucination Comparison** — Bar chart of fabrication rates per system

---

## Implementation Order

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 1 | Shared infra (S1-S3) | `hard_truth.py`, `base.py`, `runner.py` | — |
| 2 | Alive adapter (S4) | `alive_adapter.py` | S2, S3 |
| 3 | NDCG | `metrics/ndcg.py` | S1 |
| 4 | Hallucination | `metrics/hallucination.py`, `hard_truth.py`, `runner.py` | S3 |
| 5 | Consolidation ROI | `metrics/consolidation_roi.py` | — |
| 6 | Entity Confusion | `metrics/entity_confusion.py`, `hard_truth.py`, `runner.py` | S3 |
| 7 | Salience Calibration | `metrics/salience_calibration.py` | S4 |
| 8 | Cold Contribution | `metrics/cold_contribution.py` | S4 |
| 9 | Dream Evaluation | `metrics/dream_evaluation.py` | S4 |
| 10 | Graceful Degradation | `metrics/graceful_degradation.py` | S3 (p999) |
| 11 | Selective Forgetting | `metrics/selective_forgetting.py`, `base.py`, `hard_truth.py`, `runner.py`, `generate_streams.py` | S2 |
| 12 | Cross-Domain Transfer | `cross_domain.py`, `metrics/cross_domain_transfer.py`, `__main__.py` | — |
| 13 | Concurrent Latency | `concurrent_runner.py`, `metrics/concurrent_latency.py`, `__main__.py` | — |
| 14 | Report updates | `report.py` | All above |

## Verification

```bash
# Run existing tests to confirm nothing breaks
cd /Users/chulu/AI/alive-sdk && pytest tests/

# Generate fresh data
python -m benchmarks generate --scenario research_assistant

# Quick sanity run with alive adapter (1000 cycles)
python -m benchmarks run --stream research_assistant_10k --systems alive --max-cycles 1000

# Generate report with new metrics
python -m benchmarks report --results-dir benchmarks/results/ --charts

# Cross-domain test
python -m benchmarks cross-domain --train research_assistant --test customer_support --systems alive --max-cycles 1000

# Concurrent stress test
python -m benchmarks stress --systems alive --concurrency 10 --max-cycles 1000
```
