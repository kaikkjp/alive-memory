"""Academic benchmark runner.

Drives a memory system through a dataset: ingest conversations,
answer queries, collect metrics, score results.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from benchmarks.academic.harness.base import (
    BenchmarkRunResult,
    DatasetAdapter,
    EvalResult,
    MemorySystemAdapter,
    SystemMetrics,
)


class AcademicBenchmarkRunner:
    """Runs one memory system against one academic benchmark dataset."""

    def __init__(
        self,
        dataset: DatasetAdapter,
        system: MemorySystemAdapter,
        llm_config: Optional[dict] = None,
        consolidation_interval: int = 500,
    ):
        self.dataset = dataset
        self.system = system
        self.llm_config = llm_config or {}
        self.consolidation_interval = consolidation_interval

    async def run(self, seed: int = 42) -> BenchmarkRunResult:
        """Run the full benchmark pipeline."""
        print(f"  [{self.system.system_id}] Loading dataset {self.dataset.benchmark_id}...")
        sessions = self.dataset.get_sessions()
        queries = self.dataset.get_queries()
        ground_truth = self.dataset.get_ground_truth()

        print(f"  [{self.system.system_id}] {len(sessions)} sessions, {len(queries)} queries")

        # Phase 1: Ingest all conversations
        total_turns = 0
        ingest_latencies: list[float] = []

        for i, session in enumerate(sessions):
            t0 = time.perf_counter()
            await self.system.add_conversation(session)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            ingest_latencies.append(elapsed_ms)
            total_turns += len(session)

            # Periodic consolidation
            if (i + 1) % self.consolidation_interval == 0:
                await self.system.consolidate()

            if (i + 1) % 10 == 0:
                print(f"  [{self.system.system_id}] Ingested {i + 1}/{len(sessions)} sessions ({total_turns} turns)")

        # Final consolidation
        await self.system.consolidate()
        print(f"  [{self.system.system_id}] Ingestion complete: {total_turns} turns")

        # Phase 2: Answer queries
        predictions: dict[str, str] = {}
        query_latencies: list[float] = []

        for i, query in enumerate(queries):
            t0 = time.perf_counter()
            answer = await self.system.answer_query(query, self.llm_config)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            query_latencies.append(elapsed_ms)
            predictions[query.query_id] = answer

            if (i + 1) % 50 == 0:
                print(f"  [{self.system.system_id}] Answered {i + 1}/{len(queries)} queries")

        print(f"  [{self.system.system_id}] All {len(queries)} queries answered")

        # Phase 3: Evaluate
        eval_results = await self.dataset.evaluate(predictions, ground_truth)

        # Phase 4: Collect metrics
        sys_metrics = await self.system.get_metrics()
        sys_metrics.query_latencies_ms = query_latencies
        sys_metrics.ingest_latencies_ms = ingest_latencies

        # Build result
        result = BenchmarkRunResult(
            system_id=self.system.system_id,
            benchmark_id=self.dataset.benchmark_id,
            eval_results=eval_results,
            system_metrics=sys_metrics,
            config=self.llm_config,
            seed=seed,
        )

        # Aggregate scores
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
