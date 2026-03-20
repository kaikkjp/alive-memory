"""Bench phase: load prepared state + run queries only.

Zero consolidation cost — iterate on recall strategies for free
against state saved by the prepare phase.

Usage:
    python -m benchmarks.academic bench \
        --benchmark longmemeval \
        --prepared-dir benchmarks/academic/prepared/longmemeval/alive \
        --workers 16 --resume
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from benchmarks.academic.__main__ import DATASET_REGISTRY, _load_class
from benchmarks.academic.harness.base import EvalResult, GroundTruth, MemoryQuery
from benchmarks.academic.harness.runner import _aggregate, _aggregate_by_category


# ---------------------------------------------------------------------------
# State loading
# ---------------------------------------------------------------------------

async def _init_system_from_state(
    instance_dir: Path,
    config: dict,
) -> tuple:
    """Construct AliveMemorySystem from prepared state without calling setup().

    Copies the saved bench.db + memory/ to a fresh tmpdir, then manually
    wires up the system's internals to point at the copied state.

    Returns:
        (system, tmpdir_path)
    """
    from alive_memory import AliveMemory
    from benchmarks.academic.systems.alive_system import AliveMemorySystem
    from benchmarks.academic.systems.llm_utils import LLMTracker

    # Read meta for embedder type
    meta = json.loads((instance_dir / "meta.json").read_text())
    embedder_type = meta.get("embedder", "local")

    # Create working tmpdir and copy prepared state
    tmp_dir = tempfile.mkdtemp(prefix="bench_query_")
    shutil.copy2(str(instance_dir / "bench.db"), os.path.join(tmp_dir, "bench.db"))
    src_memory = instance_dir / "memory"
    if src_memory.is_dir():
        shutil.copytree(str(src_memory), os.path.join(tmp_dir, "memory"))
    else:
        os.makedirs(os.path.join(tmp_dir, "memory"), exist_ok=True)

    db_path = os.path.join(tmp_dir, "bench.db")
    memory_dir = os.path.join(tmp_dir, "memory")

    # Construct system without calling setup()
    system = AliveMemorySystem()
    system._tmp_dir = tmp_dir
    system._db_path = db_path
    system._setup_config = config
    system._tracker = LLMTracker()
    system._llm_calls = 0
    system._llm_tokens = 0
    system._turn_count = 0

    # Build SDK config (same overrides as setup())
    sdk_config = config.get("alive_config", {})
    intake = sdk_config.setdefault("intake", {})
    intake.setdefault("salience_threshold", 0.0)
    intake.setdefault("max_salience_threshold", 0.0)
    intake.setdefault("max_day_moments", 999999)

    # LLM for consolidation — not needed for bench, but answer_query
    # only uses recall + llm_answer (external httpx call), not this LLM
    llm = None

    system._memory = AliveMemory(
        storage=db_path,
        memory_dir=memory_dir,
        config=sdk_config or None,
        llm=llm,
        embedder=embedder_type,
    )
    await system._memory.initialize()

    return system, tmp_dir


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _load_completed_ids(results_dir: Path) -> set[int]:
    """Scan worker JSONL files for already-completed instance IDs."""
    done: set[int] = set()
    if not results_dir.is_dir():
        return done
    for jsonl_file in results_dir.glob("worker_*.jsonl"):
        with open(jsonl_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "instance_id" in entry and "error" not in entry:
                        done.add(entry["instance_id"])
                except json.JSONDecodeError:
                    continue
    return done


def _merge_results(results_dir: Path) -> tuple[dict[str, str], dict[str, dict]]:
    """Merge all worker JSONL files into predictions + ground_truth dicts."""
    predictions: dict[str, str] = {}
    ground_truth: dict[str, dict] = {}

    for jsonl_file in sorted(results_dir.glob("worker_*.jsonl")):
        with open(jsonl_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "error" in entry:
                        continue
                    qid = entry["query_id"]
                    predictions[qid] = entry["prediction"]
                    if "ground_truth" in entry:
                        ground_truth[qid] = entry["ground_truth"]
                except (json.JSONDecodeError, KeyError):
                    continue

    return predictions, ground_truth


# ---------------------------------------------------------------------------
# Worker — runs in a subprocess
# ---------------------------------------------------------------------------

def _bench_worker_entry(
    worker_id: int,
    instance_specs: list[dict],
    config: dict,
    llm_config: dict,
    results_dir: str,
) -> dict:
    """Entry point for each worker process."""
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    return asyncio.run(
        _bench_worker_async(worker_id, instance_specs, config, llm_config, results_dir)
    )


async def _bench_worker_async(
    worker_id: int,
    instance_specs: list[dict],
    config: dict,
    llm_config: dict,
    results_dir: str,
) -> dict:
    """Async worker: load state → answer queries for each instance."""
    results_path = Path(results_dir) / f"worker_{worker_id}.jsonl"
    results_path.parent.mkdir(parents=True, exist_ok=True)

    completed: list[int] = []
    errors: list[str] = []
    query_latencies: list[float] = []
    predictions: dict[str, str] = {}
    all_gt: dict[str, dict] = {}

    jsonl_f = open(results_path, "a")

    try:
        for idx, spec in enumerate(instance_specs):
            inst_id = spec["instance_id"]
            instance_dir = Path(spec["instance_dir"])
            queries_raw = spec["queries"]
            gt_raw = spec["ground_truth"]

            try:
                # Load system from prepared state
                system, tmp_dir = await _init_system_from_state(instance_dir, dict(config))

                # Reconstruct query objects
                queries = [MemoryQuery(**q) for q in queries_raw]

                # Answer each query
                for query in queries:
                    t0 = time.perf_counter()
                    try:
                        answer = await system.answer_query(query, llm_config)
                    except Exception as e:
                        answer = f"[error: {e}]"
                        errors.append(f"instance {inst_id} query {query.query_id}: {e}")

                    latency_ms = (time.perf_counter() - t0) * 1000
                    query_latencies.append(latency_ms)
                    predictions[query.query_id] = answer
                    all_gt.update(gt_raw)

                    # Write result line to JSONL
                    result_line = {
                        "instance_id": inst_id,
                        "query_id": query.query_id,
                        "prediction": answer,
                        "ground_truth": gt_raw.get(query.query_id, {}),
                        "query_latency_ms": latency_ms,
                        "worker_id": worker_id,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    jsonl_f.write(json.dumps(result_line) + "\n")
                    jsonl_f.flush()

                # Cleanup
                if system._memory:
                    await system._memory.close()
                if os.path.isdir(tmp_dir):
                    shutil.rmtree(tmp_dir, ignore_errors=True)

                completed.append(inst_id)
                print(
                    f"  [worker {worker_id}] instance {inst_id} done "
                    f"({idx + 1}/{len(instance_specs)})",
                    flush=True,
                )

            except Exception as e:
                errors.append(f"instance {inst_id}: {e}")
                print(f"  [worker {worker_id}] instance {inst_id} FAILED: {e}", flush=True)
                import traceback
                traceback.print_exc()
                # Write error entry
                error_line = {
                    "instance_id": inst_id,
                    "error": str(e),
                    "worker_id": worker_id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                jsonl_f.write(json.dumps(error_line) + "\n")
                jsonl_f.flush()
    finally:
        jsonl_f.close()

    return {
        "predictions": predictions,
        "ground_truth": all_gt,
        "completed": completed,
        "errors": errors,
        "query_latencies": query_latencies,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main_bench(args) -> None:
    """CLI entry point for bench command."""
    prepared_dir = Path(args.prepared_dir)
    if not prepared_dir.is_dir():
        print(f"Prepared directory not found: {prepared_dir}")
        sys.exit(1)

    # Discover prepared instances
    instance_specs: list[dict] = []
    for d in sorted(prepared_dir.iterdir()):
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        instance_specs.append({
            "instance_id": meta["instance_id"],
            "instance_dir": str(d),
            "queries": meta["queries"],
            "ground_truth": meta["ground_truth"],
        })

    if not instance_specs:
        print(f"No prepared instances found in {prepared_dir}")
        sys.exit(1)

    print(f"Found {len(instance_specs)} prepared instances", flush=True)

    # Results directory
    results_dir = Path(args.results_dir) / args.benchmark
    results_dir.mkdir(parents=True, exist_ok=True)

    # Per-run results in a subdirectory.
    # When resuming, reuse the latest existing run directory so we can
    # find previously completed instances.
    run_dir: Path | None = None
    if args.resume:
        existing_runs = sorted(results_dir.glob("run_*"), reverse=True)
        if existing_runs:
            run_dir = existing_runs[0]
    if run_dir is None:
        run_id = f"run_{int(time.time())}"
        run_dir = results_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Resume: skip completed instances
    skip_ids: set[int] = set()
    if args.resume:
        skip_ids = _load_completed_ids(run_dir)
        if skip_ids:
            print(f"Resuming: {len(skip_ids)} instances already answered", flush=True)
            instance_specs = [s for s in instance_specs if s["instance_id"] not in skip_ids]

    if not instance_specs:
        print("All instances already answered. Running evaluation only.")
    else:
        n = len(instance_specs)
        w = min(args.workers, n)

        # Build config
        config: dict = {"seed": 42}
        llm_config: dict = {}
        if args.llm_model:
            config["llm_model"] = args.llm_model
            llm_config["model"] = args.llm_model
        if args.api_key:
            config["api_key"] = args.api_key
            llm_config["api_key"] = args.api_key
        if getattr(args, "base_url", None):
            llm_config["base_url"] = args.base_url

        print(f"Benchmark: {args.benchmark}, Instances: {n}, Workers: {w}")
        print(f"Results dir: {run_dir}\n")

        # Split into chunks
        chunk_size = (n + w - 1) // w
        chunks = [instance_specs[i:i + chunk_size] for i in range(0, n, chunk_size)]
        print(f"Chunk sizes: {[len(c) for c in chunks]}")

        start = time.perf_counter()

        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=len(chunks)) as pool:
            futures = [
                loop.run_in_executor(
                    pool, _bench_worker_entry,
                    i, chunk, config, llm_config, str(run_dir),
                )
                for i, chunk in enumerate(chunks)
            ]
            results = await asyncio.gather(*futures, return_exceptions=True)

        elapsed = time.perf_counter() - start

        # Check for worker errors
        worker_errors: list[str] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                worker_errors.append(f"Worker {i} crashed: {r}")
                import traceback
                traceback.print_exception(type(r), r, r.__traceback__)

        print(f"\nAll workers done in {elapsed:.1f}s")
        if worker_errors:
            for e in worker_errors:
                print(f"  {e}")

    # Merge all JSONL results (including from previous resume runs)
    predictions, gt_raw = _merge_results(run_dir)
    print(f"Total predictions: {len(predictions)}")

    if not predictions:
        print("No predictions to evaluate.")
        return

    # Reconstruct GroundTruth objects
    all_gt = {qid: GroundTruth(**v) for qid, v in gt_raw.items()}

    # Evaluate using dataset
    if args.benchmark not in DATASET_REGISTRY:
        print(f"Unknown benchmark: {args.benchmark}")
        sys.exit(1)

    mod_path, cls_name = DATASET_REGISTRY[args.benchmark]
    dataset_cls = _load_class(mod_path, cls_name)
    dataset = dataset_cls()
    print(f"Loading dataset for evaluation...", flush=True)
    await dataset.load(args.data_dir)

    judge_config = None
    if args.judge_model:
        judge_config = {"model": args.judge_model}
        judge_key = args.judge_api_key or args.api_key
        if judge_key:
            judge_config["api_key"] = judge_key
        if args.judge_base_url:
            judge_config["base_url"] = args.judge_base_url

    eval_results = await dataset.evaluate(predictions, all_gt, judge_config=judge_config)

    agg = _aggregate(eval_results)
    by_cat = _aggregate_by_category(eval_results)

    # Compute latency stats from JSONL
    all_latencies: list[float] = []
    for jsonl_file in run_dir.glob("worker_*.jsonl"):
        with open(jsonl_file) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if "query_latency_ms" in entry:
                        all_latencies.append(entry["query_latency_ms"])
                except (json.JSONDecodeError, KeyError):
                    continue
    sorted_lat = sorted(all_latencies)

    # Print report
    print(f"\n{'=' * 50}")
    print(f"  RESULTS: {args.benchmark}")
    print(f"{'=' * 50}")
    print(f"  Aggregate: {agg}")
    print(f"  Predictions: {len(predictions)}")
    if sorted_lat:
        print(f"  Query latency (median): {sorted_lat[len(sorted_lat)//2]:.1f}ms")
        print(f"  Query latency (p95):    {sorted_lat[int(len(sorted_lat)*0.95)]:.1f}ms")
    print(f"\n  Per-category:")
    for cat, scores in sorted(by_cat.items()):
        print(f"    {cat}: {scores}")

    # Save summary
    summary = {
        "benchmark_id": args.benchmark,
        "system_id": "alive",
        "run_id": run_id,
        "seed": 42,
        "aggregate_scores": agg,
        "scores_by_category": by_cat,
        "system_metrics": {
            "total_predictions": len(predictions),
            "median_query_latency_ms": sorted_lat[len(sorted_lat)//2] if sorted_lat else 0,
            "p95_query_latency_ms": sorted_lat[int(len(sorted_lat)*0.95)] if sorted_lat else 0,
        },
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
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  Summary saved to {summary_path}")

    # Also save to the standard location for comparison with other runs
    compat_path = results_dir / "alive_bench.json"
    compat_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  Compatible result saved to {compat_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bench: load prepared state + run queries")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--prepared-dir", required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--data-dir", default="benchmarks/academic/data")
    parser.add_argument("--results-dir", default="benchmarks/academic/results")
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--judge-api-key", default=None)
    parser.add_argument("--judge-base-url", default=None)
    args = parser.parse_args()
    asyncio.run(main_bench(args))
