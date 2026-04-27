# Plan: Implement Benchmark Metrics

## Context

The alive-memory benchmark framework compares alive-memory against competitor
memory systems across recall quality, contradiction handling, scale, noise
resilience, identity, and cost. There are 11 existing gaps in the metric
coverage that would strengthen the case for alive-memory's superiority. This
plan adds those metrics and the additional autobiographical scorecard required
for the product claim.

The product claim is narrower and stronger than "better recall": alive-memory
is **autobiographical, identity-preserving, emotionally weighted memory for
persistent agents**. Future benchmark work must treat that as a first-class
metric family. Generic recall, RAG quality, and public benchmark scores are
supporting evidence; they are not enough to prove the core claim.

## Autobiographical Metric Gates

Before promoting a memory change as better for persistent agents, report these
metrics alongside the existing 11:

| Metric | Required Signal |
|--------|-----------------|
| `self_identity_stability` | Stable self traits and narrative survive long gaps, sleep, and process restart |
| `visitor_taste_currentness` | Latest active visitor preference is used and stale preferences are suppressed |
| `affective_salience_ranking` | Emotionally meaningful memories rank higher only when query intent calls for them |
| `person_boundary_integrity` | Visitor, self, relationship, and world memories do not contaminate one another |
| `narrative_grounding` | Every identity/taste/narrative claim can be traced to evidence ids |
| `change_legibility` | Corrections and identity shifts include what changed, when, and why |
| `restart_durability` | Hot memory, structured traits, and evidence links survive reload |

Minimum gate: alive-memory must beat generic RAG, summary memory, profile/fact
memory, and full-context/oracle where applicable on the autobiographical
scorecard before docs or reports claim it is better for always-on human-like
agents.

## Pre-Benchmark Fixes

Complete these before running a full comparison. They are ordered by how much
they affect whether results are defensible.

1. **Implement the autobiographical evaluator first.** The
   `autobiographical_agent_3k` stream must not be judged only by generic F1.
   Score identity consistency, taste/preference accuracy, emotional salience,
   preference updates, contradiction handling, abstention, temporal specificity,
   person-boundary integrity, and evidence grounding as separate dimensions.
2. **Prepare remaining SOTA tracks deliberately.** MemoryArena public-format
   prepare is complete for alive-memory. MemoryAgentBench public-format support
   is implemented, but its rows contain very large context strings; any chunk
   cap is a benchmark-budget decision and must be reported before claims use
   that track.
3. **Freeze competitor baselines before results.** At minimum, define whether
   the run includes alive-memory, vector RAG, summary memory, LangChain/LCB,
   Mem0, Zep/Graphiti, Mastra Observational Memory or an observation-log
   equivalent, and MemGPT/Letta-style memory. Any excluded SOTA system needs a
   written reason in the report.
4. **Freeze benchmark manifests.** Store dataset hashes, seeds, model names,
   prompts, adapter commits, dependency versions, token budgets, latency
   budgets, storage budgets, and hardware before the run starts.
5. **Audit synthetic ground truth.** Manually spot-check the autobiographical
   cases so current preferences are not confused with old preferences, and
   emotionally important items are not confused with repeated but low-salience
   items.
6. **Save recall evidence traces.** Every scored answer should include
   retrieved memory ids, timestamps, scores, source snippets, and evidence ids.
   This is required to explain both wins and regressions.
7. **Smoke every configured system.** Run a short benchmark for each system to
   catch missing dependencies, API key issues, schema drift, and output
   serialization failures before long runs.
8. **Capture cost, latency, and footprint.** Every system result should include
   ingest latency, recall latency, consolidation latency, answer latency, token
   count, estimated cost, memory count, and disk size.
9. **Declare success gates.** Recommended starting gates are: Track E composite
   beats the strongest non-oracle baseline by at least 15%, factual recall is
   not worse than vanilla RAG beyond the registered tolerance, stale-preference
   activation is lower than every non-oracle baseline, and latency/cost stay
   within the product budget.

Implementation status: the initial deterministic Track E scorer lives in
`benchmarks/scoring/autobiographical.py` and is wired into
`benchmarks/runner.py` plus `benchmarks/report.py`. It emits
`autobiographical_summary` and per-query `autobiographical_scores` in result
JSON. The runner also emits `run_manifest` dataset hashes and per-query
`recall_traces` for evidence auditing. The A1-A7 modules below can still be
split out later if the scorecard needs more specialized implementations or
charts.

MemoryAgentBench and MemoryArena public-format adapters are implemented. Full
alive-memory prepare completed for MemoryArena at 4850/4850 instances. Smoke
prepare passed for MemoryAgentBench with `ALIVE_BENCH_HF_MAX_ROWS=1` plus
`ALIVE_BENCH_MAX_CONTEXT_CHUNKS=2`.

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

## Autobiographical Metric Modules

These modules are required for the owned persistent-agent track in
`docs/BENCHMARK_SPEC.md`. They depend on adapters preserving `agent_id`,
`visitor_id`, `session_id`, `turn_index`, `identity_scope`, affect fields, and
`evidence_ids`.

### A1. `self_identity_stability.py`: Durable Agent Self
```
SelfIdentityStabilityResult: stability_score, drift_without_evidence_rate, restart_survival, supported
compute_self_identity_stability(result: BenchmarkResult) -> SelfIdentityStabilityResult
```
- Compare self-model snapshots before/after long gaps, sleep, and restart
- Penalize identity changes not supported by repeated evidence ids
- Score style, values, tastes, and durable self-description separately

### A2. `visitor_taste_currentness.py`: Current Preferences
```
VisitorTasteCurrentnessResult: currentness_score, stale_preference_rate, supersession_accuracy, supported
compute_visitor_taste_currentness(result: BenchmarkResult) -> VisitorTasteCurrentnessResult
```
- For each visitor, check whether current active tastes beat stale tastes
- Explicit corrections are strict failures if old preferences remain active
- Multi-visitor cases must evaluate each visitor independently

### A3. `affective_salience_ranking.py`: Emotional Weight Without Pollution
```
AffectiveSalienceRankingResult: relevant_affect_ndcg, pollution_rate, valence_update_accuracy, supported
compute_affective_salience_ranking(result: BenchmarkResult) -> AffectiveSalienceRankingResult
```
- Use NDCG on emotionally meaningful items for affective/autobiographical queries
- Penalize surfacing emotional memories for unrelated factual queries
- Track updates where an event's emotional meaning changes over time

### A4. `person_boundary_integrity.py`: Scope Isolation
```
PersonBoundaryIntegrityResult: boundary_score, leakage_rate, confused_pairs, supported
compute_person_boundary_integrity(result: BenchmarkResult) -> PersonBoundaryIntegrityResult
```
- Detect Alice/Bob/self/world contamination in retrieved memories and answers
- Report most-confused identity pairs, not just aggregate rate
- Treat shared projects separately from personal tastes

### A5. `narrative_grounding.py`: Evidence-Backed Identity Narrative
```
NarrativeGroundingResult: grounded_claim_rate, unsupported_claim_rate, evidence_coverage, supported
compute_narrative_grounding(result: BenchmarkResult) -> NarrativeGroundingResult
```
- Extract claims from generated identity or visitor narratives
- Every claim must map to one or more evidence ids
- LLM judging is allowed only after deterministic evidence checks pass

### A6. `change_legibility.py`: Why the Self or Taste Changed
```
ChangeLegibilityResult: change_detection_rate, explanation_accuracy, stale_state_suppression, supported
compute_change_legibility(result: BenchmarkResult) -> ChangeLegibilityResult
```
- Score whether the system identifies what changed, when, and why
- Corrections should produce active/superseded state, not competing facts
- One-off transient affect should not rewrite durable identity

### A7. `restart_durability.py`: Persistent Memory Integrity
```
RestartDurabilityResult: hot_memory_survival, structured_state_survival, evidence_link_survival, supported
compute_restart_durability(result: BenchmarkResult) -> RestartDurabilityResult
```
- Run ingest, sleep, save, reload, and recall in the same benchmark case
- Verify hot markdown, SQLite state, and evidence links survive restart
- Fail hard if `memory_dir` is temporary in a persistent-agent run

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

Add 5 new sections to `generate_markdown()`:
1. **Ranking Quality** — NDCG@5 table by system + by category
2. **Reliability** — Hallucination rate + entity confusion rate table
3. **Efficiency** — Consolidation ROI table + graceful degradation
4. **alive-memory Specific** — Salience calibration, cold contribution, dream evaluation (only shown if data present)
5. **Autobiographical Memory** - self-identity stability, visitor taste currentness, affective salience, person-boundary integrity, narrative grounding, change legibility, restart durability

Add 3 new charts to `generate_charts()`:
1. **ROI Frontier** — F1 improvement vs cost scatter (like cost_quality but shows improvement delta)
2. **Hallucination Comparison** — Bar chart of fabrication rates per system
3. **Autobiographical Scorecard** - Radar or grouped bar chart for Track E metrics

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
| 11 | Autobiographical metric data plumbing | `base.py`, `runner.py`, `hard_truth.py`, adapters | S2, S3 |
| 12 | Autobiographical metrics A1-A7 | `metrics/self_identity_stability.py`, `metrics/visitor_taste_currentness.py`, `metrics/affective_salience_ranking.py`, `metrics/person_boundary_integrity.py`, `metrics/narrative_grounding.py`, `metrics/change_legibility.py`, `metrics/restart_durability.py` | Step 11 |
| 13 | Selective Forgetting | `metrics/selective_forgetting.py`, `base.py`, `hard_truth.py`, `runner.py`, `generate_streams.py` | S2 |
| 14 | Cross-Domain Transfer | `cross_domain.py`, `metrics/cross_domain_transfer.py`, `__main__.py` | none |
| 15 | Concurrent Latency | `concurrent_runner.py`, `metrics/concurrent_latency.py`, `__main__.py` | none |
| 16 | Report updates | `report.py` | All above |

## Verification

```bash
# Run existing tests to confirm nothing breaks
cd /Users/chulu/AI/alive-memory && pytest tests/

# Generate fresh data
python -m benchmarks generate --scenario research_assistant

# Quick sanity run with alive adapter (1000 cycles)
python -m benchmarks run --stream research_assistant_10k --systems alive --max-cycles 1000

# Generate report with new metrics
python -m benchmarks report --results-dir benchmarks/results/ --charts

# Autobiographical persistent-agent suite
python -m benchmarks generate --scenario autobiographical_agent
python -m benchmarks run --stream autobiographical_agent_3k --systems alive,rag,lcs,mem0,zep --max-cycles 1000

# Cross-domain test
python -m benchmarks cross-domain --train research_assistant --test customer_support --systems alive --max-cycles 1000

# Concurrent stress test
python -m benchmarks stress --systems alive --concurrency 10 --max-cycles 1000
```
