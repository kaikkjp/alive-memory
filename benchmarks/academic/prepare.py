"""Prepare phase: ingest + consolidate + save state per instance.

Expensive consolidation runs once. State is saved to disk so the bench
phase can reload it and iterate on recall strategies for free.

Usage:
    python -m benchmarks.academic prepare \
        --benchmark longmemeval --system alive --workers 16 --resume
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from benchmarks.academic.__main__ import DATASET_REGISTRY, SYSTEM_REGISTRY, _load_class
from benchmarks.academic.parallel_run import _serialize_instances


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _checkpoint_db(db_path: str) -> None:
    """Fold WAL into main DB file, remove WAL/SHM."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)


def _save_instance_state(
    tmp_dir: str,
    instance_dir: Path,
    instance_id: int,
    queries_serialized: list[dict],
    ground_truth_serialized: dict[str, dict],
    num_sessions: int,
    num_turns: int,
    ingest_ms: float,
    consolidate_ms: float,
    embedder_type: str,
    hot_memory_tokens: int = 0,
    cold_count: int = 0,
) -> dict:
    """Atomically save consolidated state to instance_dir. Returns meta dict."""
    staging = instance_dir.parent / f".staging_{instance_dir.name}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # Copy database
    src_db = os.path.join(tmp_dir, "bench.db")
    if os.path.exists(src_db):
        shutil.copy2(src_db, str(staging / "bench.db"))
        # Copy WAL/SHM if they exist
        for suffix in ("-wal", "-shm"):
            src = src_db + suffix
            if os.path.exists(src):
                shutil.copy2(src, str(staging / f"bench.db{suffix}"))
        _checkpoint_db(str(staging / "bench.db"))

    # Copy hot memory directory
    src_memory = os.path.join(tmp_dir, "memory")
    if os.path.isdir(src_memory):
        shutil.copytree(src_memory, str(staging / "memory"))

    # Compute sizes
    db_size = 0
    db_path = staging / "bench.db"
    if db_path.exists():
        db_size = db_path.stat().st_size

    mem_size = 0
    mem_dir = staging / "memory"
    if mem_dir.is_dir():
        mem_size = sum(f.stat().st_size for f in mem_dir.rglob("*") if f.is_file())

    meta = {
        "instance_id": instance_id,
        "num_sessions": num_sessions,
        "num_turns": num_turns,
        "queries": queries_serialized,
        "ground_truth": ground_truth_serialized,
        "hot_memory_tokens": hot_memory_tokens,
        "cold_memory_count": cold_count,
        "db_size_bytes": db_size,
        "memory_dir_size_bytes": mem_size,
        "ingest_ms": ingest_ms,
        "consolidate_ms": consolidate_ms,
        "embedder": embedder_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (staging / "meta.json").write_text(json.dumps(meta, indent=2))

    # Atomic rename
    if instance_dir.exists():
        shutil.rmtree(instance_dir)
    staging.rename(instance_dir)

    return meta


def _update_progress(progress_path: Path, new_completed: list[int], new_failed: list[int]) -> None:
    """Atomically update progress.json."""
    data: dict = {}
    if progress_path.exists():
        data = json.loads(progress_path.read_text())

    completed = set(data.get("prepared_instances", []))
    failed = set(data.get("failed_instances", []))

    completed.update(new_completed)
    # Remove newly completed from failed
    failed -= set(new_completed)
    failed.update(new_failed)

    data["prepared_instances"] = sorted(completed)
    data["failed_instances"] = sorted(failed)
    data["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    tmp = progress_path.parent / ".progress.json.tmp"
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(progress_path)


# ---------------------------------------------------------------------------
# Worker — runs in a subprocess
# ---------------------------------------------------------------------------

def _prepare_worker_entry(
    worker_id: int,
    instances_serialized: list[dict],
    instance_ids: list[int],
    system_module: str,
    system_class: str,
    config: dict,
    output_dir: str,
    skip_ids: list[int],
) -> dict:
    """Entry point for each worker process."""
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    return asyncio.run(
        _prepare_worker_async(
            worker_id, instances_serialized, instance_ids,
            system_module, system_class, config, output_dir, skip_ids,
        )
    )


async def _prepare_worker_async(
    worker_id: int,
    instances_serialized: list[dict],
    instance_ids: list[int],
    system_module: str,
    system_class: str,
    config: dict,
    output_dir: str,
    skip_ids: list[int],
) -> dict:
    """Async worker: ingest → consolidate → save for each instance."""
    import importlib
    from benchmarks.academic.harness.base import ConversationTurn

    skip_set = set(skip_ids)

    mod = importlib.import_module(system_module)
    system_cls = getattr(mod, system_class)

    completed: list[int] = []
    failed: list[int] = []
    errors: list[str] = []
    skipped = 0

    out_path = Path(output_dir)

    for idx, (inst, inst_id) in enumerate(zip(instances_serialized, instance_ids)):
        # Check if already prepared
        instance_dir = out_path / f"instance_{inst_id:03d}"
        if inst_id in skip_set or (instance_dir / "meta.json").exists():
            skipped += 1
            print(f"  [worker {worker_id}] instance {inst_id} already prepared, skipping", flush=True)
            continue

        try:
            # Setup fresh system
            system = system_cls()
            await system.setup(dict(config))

            # Deserialize sessions
            sessions = [
                [ConversationTurn(**t) for t in sess]
                for sess in inst["sessions"]
            ]
            num_sessions = len(sessions)
            num_turns = sum(len(s) for s in sessions)

            # Ingest all sessions
            t_ingest = time.perf_counter()
            for session in sessions:
                await system.add_conversation(session)
            ingest_ms = (time.perf_counter() - t_ingest) * 1000

            # Consolidate
            t_cons = time.perf_counter()
            await system.consolidate()
            consolidate_ms = (time.perf_counter() - t_cons) * 1000

            # Measure hot memory tokens
            hot_tokens = 0
            if hasattr(system, "_memory") and system._memory and hasattr(system._memory, "_writer"):
                hot_tokens = system._memory._writer.total_token_estimate()

            # Measure cold entries
            cold_count = 0
            if hasattr(system, "_memory") and system._memory and hasattr(system._memory, "_storage"):
                try:
                    rows = await system._memory._storage._db.execute_fetchall(
                        "SELECT COUNT(*) FROM cold_memory"
                    )
                    cold_count = rows[0][0] if rows else 0
                except Exception:
                    pass

            # Determine embedder type
            embedder_type = "local"
            if os.environ.get("OPENAI_API_KEY"):
                embedder_type = "openai"

            # Close DB to flush WAL before copying
            if hasattr(system, "_memory") and system._memory:
                await system._memory.close()

            # Save state
            meta = _save_instance_state(
                tmp_dir=system._tmp_dir,
                instance_dir=instance_dir,
                instance_id=inst_id,
                queries_serialized=inst["queries"],
                ground_truth_serialized=inst["ground_truth"],
                num_sessions=num_sessions,
                num_turns=num_turns,
                ingest_ms=ingest_ms,
                consolidate_ms=consolidate_ms,
                embedder_type=embedder_type,
                hot_memory_tokens=hot_tokens,
                cold_count=cold_count,
            )

            completed.append(inst_id)
            print(
                f"  [worker {worker_id}] instance {inst_id} done "
                f"({idx + 1 - skipped}/{len(instances_serialized) - skipped}) "
                f"— {hot_tokens:,} hot tokens, {cold_count} cold entries, "
                f"consolidate {consolidate_ms:.0f}ms",
                flush=True,
            )

            # Cleanup tmpdir
            if system._tmp_dir and os.path.isdir(system._tmp_dir):
                shutil.rmtree(system._tmp_dir, ignore_errors=True)

        except Exception as e:
            failed.append(inst_id)
            errors.append(f"instance {inst_id}: {e}")
            print(f"  [worker {worker_id}] instance {inst_id} FAILED: {e}", flush=True)
            import traceback
            traceback.print_exc()

    return {
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main_prepare(args) -> None:
    """CLI entry point for prepare command."""
    if args.benchmark not in DATASET_REGISTRY:
        print(f"Unknown benchmark: {args.benchmark}")
        print(f"Available: {', '.join(DATASET_REGISTRY)}")
        sys.exit(1)

    if args.system not in SYSTEM_REGISTRY:
        print(f"Unknown system: {args.system}")
        print(f"Available: {', '.join(SYSTEM_REGISTRY)}")
        sys.exit(1)

    # Load dataset
    mod_path, cls_name = DATASET_REGISTRY[args.benchmark]
    dataset_cls = _load_class(mod_path, cls_name)
    dataset = dataset_cls()
    print(f"Loading dataset {args.benchmark}...", flush=True)
    await dataset.load(args.data_dir)

    instances = dataset.get_instances()
    n = len(instances)

    # Output directory
    output_dir = Path(args.output_dir) / args.benchmark / args.system
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.json"

    # Check what's already prepared (resume)
    skip_ids: set[int] = set()
    if args.resume:
        for i in range(n):
            meta_path = output_dir / f"instance_{i:03d}" / "meta.json"
            if meta_path.exists():
                skip_ids.add(i)
        if skip_ids:
            print(f"Resuming: {len(skip_ids)}/{n} instances already prepared", flush=True)

    remaining = n - len(skip_ids)
    if remaining == 0:
        print("All instances already prepared. Nothing to do.")
        return

    w = min(args.workers, remaining)
    print(f"Benchmark: {args.benchmark}, System: {args.system}")
    print(f"Total instances: {n}, Remaining: {remaining}, Workers: {w}")

    # Build config
    config: dict = {"seed": 42}
    if args.llm_model:
        config["llm_model"] = args.llm_model
    if args.api_key:
        config["api_key"] = args.api_key

    sys_mod, sys_cls = SYSTEM_REGISTRY[args.system]

    # Assign instance IDs and serialize
    all_ids = [i for i in range(n) if i not in skip_ids]
    all_instances = [instances[i] for i in all_ids]

    chunk_size = (len(all_ids) + w - 1) // w
    id_chunks = [all_ids[i:i + chunk_size] for i in range(0, len(all_ids), chunk_size)]
    inst_chunks = [all_instances[i:i + chunk_size] for i in range(0, len(all_instances), chunk_size)]
    ser_chunks = [_serialize_instances(c) for c in inst_chunks]

    print(f"Chunk sizes: {[len(c) for c in id_chunks]}")
    print(f"Output dir: {output_dir}\n")

    start = time.perf_counter()

    skip_list = sorted(skip_ids)
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=len(id_chunks)) as pool:
        futures = [
            loop.run_in_executor(
                pool, _prepare_worker_entry,
                i, ser_chunk, id_chunk,
                sys_mod, sys_cls, config, str(output_dir), skip_list,
            )
            for i, (ser_chunk, id_chunk) in enumerate(zip(ser_chunks, id_chunks))
        ]
        results = await asyncio.gather(*futures, return_exceptions=True)

    elapsed = time.perf_counter() - start

    # Merge results and update progress
    all_completed: list[int] = []
    all_failed: list[int] = []
    all_errors: list[str] = []
    total_skipped = 0

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            all_errors.append(f"Worker {i} crashed: {r}")
            import traceback
            traceback.print_exception(type(r), r, r.__traceback__)
            continue
        all_completed.extend(r["completed"])
        all_failed.extend(r["failed"])
        all_errors.extend(r["errors"])
        total_skipped += r["skipped"]

    _update_progress(progress_path, all_completed, all_failed)

    # Summary
    total_prepared = len(skip_ids) + len(all_completed)
    print(f"\n{'=' * 50}")
    print(f"  PREPARE COMPLETE")
    print(f"{'=' * 50}")
    print(f"  Prepared: {total_prepared}/{n} instances")
    print(f"  New:      {len(all_completed)}")
    print(f"  Skipped:  {total_skipped}")
    print(f"  Failed:   {len(all_failed)}")
    print(f"  Time:     {elapsed:.1f}s")
    print(f"  Output:   {output_dir}")

    if all_errors:
        print(f"\n  Errors:")
        for e in all_errors:
            print(f"    {e}")

    # Print hot memory stats from completed instances
    hot_sizes = []
    cold_counts = []
    for inst_id in all_completed:
        meta_path = output_dir / f"instance_{inst_id:03d}" / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            hot_sizes.append(meta.get("hot_memory_tokens", 0))
            cold_counts.append(meta.get("cold_memory_count", 0))

    if hot_sizes:
        print(f"\n  Hot memory tokens: min={min(hot_sizes):,}, max={max(hot_sizes):,}, avg={sum(hot_sizes)//len(hot_sizes):,}")
        print(f"  Cold entries:      min={min(cold_counts)}, max={max(cold_counts)}, avg={sum(cold_counts)//len(cold_counts)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prepare benchmark instances (ingest + consolidate + save)")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--system", default="alive")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--data-dir", default="benchmarks/academic/data")
    parser.add_argument("--output-dir", default="benchmarks/academic/prepared")
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_prepare(args))
