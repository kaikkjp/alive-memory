"""Parallel benchmark runner — splits questions across N worker processes.

Each worker runs in a separate OS process with its own asyncio event loop,
giving true CPU parallelism via ProcessPoolExecutor.

Usage:
    python -m benchmarks.academic.parallel_run \
        --benchmark longmemeval --system alive --workers 16
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# Add repo root to path so worker processes can import
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, _REPO_ROOT)

from benchmarks.academic.__main__ import DATASET_REGISTRY, SYSTEM_REGISTRY, _load_class
from benchmarks.academic.harness.base import GroundTruth
from benchmarks.academic.harness.runner import _aggregate, _aggregate_by_category


# ---------------------------------------------------------------------------
# Worker — runs in a subprocess
# ---------------------------------------------------------------------------

def _worker_entry(
    worker_id: int,
    instances_serialized: list[dict],
    system_module: str,
    system_class: str,
    config: dict,
    llm_config: dict,
) -> dict:
    """Entry point for each worker process. Calls asyncio.run internally."""
    # Ensure repo is on path in subprocess
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)

    return asyncio.run(
        _worker_async(worker_id, instances_serialized, system_module, system_class, config, llm_config)
    )


async def _worker_async(
    worker_id: int,
    instances_serialized: list[dict],
    system_module: str,
    system_class: str,
    config: dict,
    llm_config: dict,
) -> dict:
    """Async worker: ingest → consolidate → query for each instance."""
    import importlib
    from benchmarks.academic.harness.base import ConversationTurn, GroundTruth, MemoryQuery

    mod = importlib.import_module(system_module)
    system_cls = getattr(mod, system_class)
    system = system_cls()
    await system.setup(dict(config))

    predictions: dict[str, str] = {}
    all_gt: dict[str, GroundTruth] = {}
    total_turns = 0
    query_latencies: list[float] = []
    consolidate_latencies: list[float] = []
    ingest_latencies: list[float] = []

    for idx, inst in enumerate(instances_serialized):
        # Deserialize sessions
        sessions = [
            [ConversationTurn(**t) for t in sess]
            for sess in inst["sessions"]
        ]
        queries = [MemoryQuery(**q) for q in inst["queries"]]
        ground_truth = {
            qid: GroundTruth(**gt) for qid, gt in inst["ground_truth"].items()
        }
        all_gt.update(ground_truth)

        # Ingest
        for session in sessions:
            t0 = time.perf_counter()
            await system.add_conversation(session)
            ingest_latencies.append((time.perf_counter() - t0) * 1000)
            total_turns += len(session)

        # Consolidate
        t0 = time.perf_counter()
        await system.consolidate()
        consolidate_latencies.append((time.perf_counter() - t0) * 1000)

        # Query
        for query in queries:
            t0 = time.perf_counter()
            answer = await system.answer_query(query, llm_config)
            query_latencies.append((time.perf_counter() - t0) * 1000)
            predictions[query.query_id] = answer

        done = idx + 1
        print(f"  [worker {worker_id}] {done}/{len(instances_serialized)} instances done", flush=True)

        # Reset for next instance
        if idx < len(instances_serialized) - 1:
            await system.reset()

    metrics = await system.get_metrics()
    await system.teardown()

    return {
        "predictions": predictions,
        "ground_truth": {qid: {"query_id": gt.query_id, "answer": gt.answer, "category": gt.category}
                         for qid, gt in all_gt.items()},
        "total_turns": total_turns,
        "query_latencies": query_latencies,
        "consolidate_latencies": consolidate_latencies,
        "ingest_latencies": ingest_latencies,
        "llm_calls": metrics.total_llm_calls,
        "tokens": metrics.total_tokens,
        "storage": metrics.storage_bytes,
        "memory_count": metrics.memory_count,
    }


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_instances(instances: list) -> list[dict]:
    """Convert instances to plain dicts for cross-process pickling."""
    out = []
    for sessions, queries, ground_truth in instances:
        out.append({
            "sessions": [
                [
                    {
                        "role": t.role,
                        "content": t.content,
                        "turn_id": t.turn_id,
                        "session_id": t.session_id,
                        "timestamp": t.timestamp,
                        "metadata": t.metadata,
                    }
                    for t in sess
                ]
                for sess in sessions
            ],
            "queries": [
                {
                    "query_id": q.query_id,
                    "question": q.question,
                    "category": q.category,
                    "session_id": q.session_id,
                    "metadata": q.metadata,
                }
                for q in queries
            ],
            "ground_truth": {
                qid: {"query_id": gt.query_id, "answer": gt.answer, "category": gt.category}
                for qid, gt in ground_truth.items()
            },
        })
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Parallel benchmark runner (multiprocess)")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--system", default="alive")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--data-dir", default="benchmarks/academic/data")
    parser.add_argument("--results-dir", default="benchmarks/academic/results")
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    # Load dataset in main process
    mod_path, cls_name = DATASET_REGISTRY[args.benchmark]
    dataset_cls = _load_class(mod_path, cls_name)
    dataset = dataset_cls()
    await dataset.load(args.data_dir)

    instances = dataset.get_instances()
    n = len(instances)
    w = min(args.workers, n)
    print(f"Benchmark: {args.benchmark}, System: {args.system}")
    print(f"Total instances: {n}, Workers: {w}")

    # Split and serialize
    chunk_size = (n + w - 1) // w
    chunks_raw = [instances[i:i + chunk_size] for i in range(0, n, chunk_size)]
    chunks = [_serialize_instances(c) for c in chunks_raw]
    print(f"Chunk sizes: {[len(c) for c in chunks]}\n")

    sys_mod, sys_cls = SYSTEM_REGISTRY[args.system]
    config: dict = {"seed": 42}
    llm_config: dict = {}
    if args.llm_model:
        config["llm_model"] = args.llm_model
        llm_config["model"] = args.llm_model
    if args.api_key:
        config["api_key"] = args.api_key
        llm_config["api_key"] = args.api_key

    print(f"Starting {len(chunks)} worker processes...")
    start = time.perf_counter()

    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=len(chunks)) as pool:
        futures = [
            loop.run_in_executor(pool, _worker_entry, i, chunk, sys_mod, sys_cls, config, llm_config)
            for i, chunk in enumerate(chunks)
        ]
        results = await asyncio.gather(*futures, return_exceptions=True)

    elapsed = time.perf_counter() - start
    print(f"\nAll workers done in {elapsed:.1f}s")

    # Merge
    all_predictions: dict[str, str] = {}
    all_gt_raw: dict[str, dict] = {}
    total_llm_calls = 0
    total_tokens = 0
    max_storage = 0
    max_memory = 0
    all_query_lat: list[float] = []
    all_consolidate_lat: list[float] = []

    errors = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            errors.append(f"Worker {i}: {r}")
            import traceback
            traceback.print_exception(type(r), r, r.__traceback__)
            continue
        all_predictions.update(r["predictions"])
        all_gt_raw.update(r["ground_truth"])
        total_llm_calls += r["llm_calls"]
        total_tokens += r["tokens"]
        max_storage = max(max_storage, r["storage"])
        max_memory = max(max_memory, r["memory_count"])
        all_query_lat.extend(r["query_latencies"])
        all_consolidate_lat.extend(r["consolidate_latencies"])

    if errors:
        print(f"\n{len(errors)} worker errors:")
        for e in errors:
            print(f"  {e}")

    # Reconstruct GroundTruth objects for evaluation
    from benchmarks.academic.harness.base import GroundTruth
    all_gt = {qid: GroundTruth(**v) for qid, v in all_gt_raw.items()}

    # Evaluate
    print(f"\nEvaluating {len(all_predictions)} predictions...")
    eval_results = await dataset.evaluate(all_predictions, all_gt)

    agg = _aggregate(eval_results)
    by_cat = _aggregate_by_category(eval_results)

    print(f"\n{'=' * 50}")
    print(f"  RESULTS: {args.system} on {args.benchmark}")
    print(f"{'=' * 50}")
    print(f"  Aggregate: {agg}")
    print(f"  LLM calls: {total_llm_calls}")
    print(f"  Tokens:    {total_tokens}")
    print(f"  Wall time: {elapsed:.1f}s")
    print(f"\n  Per-category:")
    for cat, scores in sorted(by_cat.items()):
        print(f"    {cat}: {scores}")

    # Save
    results_dir = Path(args.results_dir) / args.benchmark
    results_dir.mkdir(parents=True, exist_ok=True)
    result_path = results_dir / f"{args.system}.json"

    sorted_lat = sorted(all_query_lat)
    sorted_cons = sorted(all_consolidate_lat)

    data = {
        "system_id": args.system,
        "benchmark_id": args.benchmark,
        "seed": 42,
        "aggregate_scores": agg,
        "scores_by_category": by_cat,
        "system_metrics": {
            "total_llm_calls": total_llm_calls,
            "total_tokens": total_tokens,
            "storage_bytes": max_storage,
            "memory_count": max_memory,
            "median_query_latency_ms": sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0,
            "p95_query_latency_ms": sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0,
            "median_consolidate_latency_ms": sorted_cons[len(sorted_cons) // 2] if sorted_cons else 0,
            "p95_consolidate_latency_ms": sorted_cons[int(len(sorted_cons) * 0.95)] if sorted_cons else 0,
            "wall_time_seconds": elapsed,
            "workers": len(chunks),
        },
        "config": llm_config,
        "eval_results": [
            {
                "query_id": r.query_id,
                "category": r.category,
                "predicted": r.predicted,
                "expected": r.expected,
                "scores": r.scores,
            }
            for r in eval_results
        ],
    }
    result_path.write_text(json.dumps(data, indent=2, default=str))
    print(f"\n  Result saved to {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
