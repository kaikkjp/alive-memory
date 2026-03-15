"""Academic benchmark runner.

Drives a memory system through a dataset: ingest conversations,
answer queries, collect metrics, score results.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from benchmarks.academic.harness.base import (
    BenchmarkRunResult,
    DatasetAdapter,
    EvalResult,
    GroundTruth,
    MemorySystemAdapter,
)


class AcademicBenchmarkRunner:
    """Runs one memory system against one academic benchmark dataset."""

    def __init__(
        self,
        dataset: DatasetAdapter,
        system: MemorySystemAdapter,
        llm_config: dict | None = None,
        consolidation_interval: int = 500,
        reset_between_sessions: bool = False,
        judge_config: dict | None = None,
    ):
        self.dataset = dataset
        self.system = system
        self.llm_config = llm_config or {}
        self.consolidation_interval = consolidation_interval
        self.reset_between_sessions = reset_between_sessions
        self.judge_config = judge_config

    async def run(self, seed: int = 42) -> BenchmarkRunResult:
        """Run the full benchmark pipeline.

        Uses get_instances() to obtain independent evaluation units.
        The system is reset between instances to prevent cross-contamination.
        Within each instance, sessions are ingested and then queries answered.
        """
        print(f"  [{self.system.system_id}] Loading dataset {self.dataset.benchmark_id}...")
        instances = self.dataset.get_instances()
        total_queries = sum(len(qs) for _, qs, _ in instances)

        print(f"  [{self.system.system_id}] {len(instances)} instances, {total_queries} queries")

        total_turns = 0
        ingest_latencies: list[float] = []
        consolidate_latencies: list[float] = []
        predictions: dict[str, str] = {}
        query_latencies: list[float] = []
        all_ground_truth: dict[str, GroundTruth] = {}

        # Track cumulative system metrics across instances
        cumulative_llm_calls = 0
        cumulative_tokens = 0
        cumulative_storage = 0
        cumulative_memory_count = 0

        for inst_idx, (sessions, queries, ground_truth) in enumerate(instances):
            all_ground_truth.update(ground_truth)

            # Ingest all sessions for this instance
            for i, session in enumerate(sessions):
                t0 = time.perf_counter()
                await self.system.add_conversation(session)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                ingest_latencies.append(elapsed_ms)
                total_turns += len(session)

                # Periodic consolidation
                if (i + 1) % self.consolidation_interval == 0:
                    t0 = time.perf_counter()
                    await self.system.consolidate()
                    consolidate_latencies.append((time.perf_counter() - t0) * 1000)

            # Consolidate before answering queries
            t0 = time.perf_counter()
            await self.system.consolidate()
            consolidate_latencies.append((time.perf_counter() - t0) * 1000)

            # Answer all queries for this instance
            for query in queries:
                t0 = time.perf_counter()
                answer = await self.system.answer_query(query, self.llm_config)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                query_latencies.append(elapsed_ms)
                predictions[query.query_id] = answer

            # Capture metrics before reset (reset clears counters)
            if inst_idx < len(instances) - 1:
                inst_metrics = await self.system.get_metrics()
                cumulative_llm_calls += inst_metrics.total_llm_calls
                cumulative_tokens += inst_metrics.total_tokens
                cumulative_storage = max(cumulative_storage, inst_metrics.storage_bytes)
                cumulative_memory_count = max(cumulative_memory_count, inst_metrics.memory_count)
                await self.system.reset()

            answered = len(predictions)
            print(f"  [{self.system.system_id}] Instance {inst_idx + 1}/{len(instances)}: "
                  f"{len(sessions)} sessions, {len(queries)} queries, "
                  f"{answered} total answered")

        print(f"  [{self.system.system_id}] Done: {total_turns} turns, {len(predictions)} queries answered")

        # Evaluate
        if self.judge_config:
            print(f"  [{self.system.system_id}] Running LLM-as-Judge evaluation...")
        eval_results = await self.dataset.evaluate(
            predictions, all_ground_truth, judge_config=self.judge_config,
        )

        # Collect metrics (last instance + cumulative from earlier instances)
        sys_metrics = await self.system.get_metrics()
        sys_metrics.total_llm_calls += cumulative_llm_calls
        sys_metrics.total_tokens += cumulative_tokens
        sys_metrics.storage_bytes = max(sys_metrics.storage_bytes, cumulative_storage)
        sys_metrics.memory_count = max(sys_metrics.memory_count, cumulative_memory_count)
        sys_metrics.query_latencies_ms = query_latencies
        sys_metrics.ingest_latencies_ms = ingest_latencies
        sys_metrics.consolidate_latencies_ms = consolidate_latencies

        # Build result
        result = BenchmarkRunResult(
            system_id=self.system.system_id,
            benchmark_id=self.dataset.benchmark_id,
            eval_results=eval_results,
            system_metrics=sys_metrics,
            config=self.llm_config,
            seed=seed,
        )

        result.aggregate_scores = _aggregate(eval_results)
        result.scores_by_category = _aggregate_by_category(eval_results)

        return result


def _aggregate(results: list[EvalResult]) -> dict[str, float]:
    """Average all scores across results."""
    if not results:
        return {}
    all_keys: set[str] = set()
    for r in results:
        all_keys.update(r.scores.keys())

    agg = {}
    for key in sorted(all_keys):
        vals = [r.scores[key] for r in results if key in r.scores]
        agg[key] = sum(vals) / len(vals) if vals else 0.0
    return agg


def _aggregate_by_category(results: list[EvalResult]) -> dict[str, dict[str, float]]:
    """Average scores grouped by category."""
    by_cat: dict[str, list[EvalResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)
    return {cat: _aggregate(rs) for cat, rs in sorted(by_cat.items())}


def save_result(result: BenchmarkRunResult, path: str) -> None:
    """Save benchmark result to JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "system_id": result.system_id,
        "benchmark_id": result.benchmark_id,
        "seed": result.seed,
        "aggregate_scores": result.aggregate_scores,
        "scores_by_category": result.scores_by_category,
        "system_metrics": {
            "total_llm_calls": result.system_metrics.total_llm_calls,
            "total_tokens": result.system_metrics.total_tokens,
            "storage_bytes": result.system_metrics.storage_bytes,
            "memory_count": result.system_metrics.memory_count,
            "median_query_latency_ms": result.system_metrics.median_query_latency_ms,
            "p95_query_latency_ms": result.system_metrics.p95_query_latency_ms,
            "median_consolidate_latency_ms": result.system_metrics.median_consolidate_latency_ms,
            "p95_consolidate_latency_ms": result.system_metrics.p95_consolidate_latency_ms,
        },
        "config": result.config,
        "eval_results": [
            {
                "query_id": r.query_id,
                "category": r.category,
                "predicted": r.predicted,
                "expected": r.expected,
                "scores": r.scores,
            }
            for r in result.eval_results
        ],
    }
    p.write_text(json.dumps(data, indent=2, default=str))
    print(f"  Result saved to {path}")
