"""CLI entry point for the academic benchmark suite.

Usage:
    python -m benchmarks.academic run --benchmark locomo --systems alive,rag
    python -m benchmarks.academic run --benchmark longmemeval --all
    python -m benchmarks.academic run --benchmark locomo --all --judge-model anthropic/claude-haiku-4-5
    python -m benchmarks.academic list
    python -m benchmarks.academic report --results-dir benchmarks/academic/results/

    # Two-phase workflow: prepare once, bench many times
    python -m benchmarks.academic prepare --benchmark longmemeval --system alive --workers 16
    python -m benchmarks.academic bench --benchmark longmemeval --prepared-dir prepared/longmemeval/alive --workers 16
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

DATASET_REGISTRY = {
    "locomo": ("benchmarks.academic.datasets.locomo", "LoCoMoDataset"),
    "longmemeval": ("benchmarks.academic.datasets.longmemeval", "LongMemEvalDataset"),
    "memoryagentbench": (
        "benchmarks.academic.datasets.memoryagentbench",
        "MemoryAgentBenchDataset",
    ),
    "memoryarena": ("benchmarks.academic.datasets.memoryarena", "MemoryArenaDataset"),
}

SYSTEM_REGISTRY = {
    "no-memory": ("benchmarks.academic.systems.no_memory", "NoMemorySystem"),
    "full-context": ("benchmarks.academic.systems.full_context", "FullContextSystem"),
    "summary": ("benchmarks.academic.systems.summary_memory", "SummaryMemorySystem"),
    "rag": ("benchmarks.academic.systems.rag_memory", "RAGMemorySystem"),
    "alive": ("benchmarks.academic.systems.alive_system", "AliveMemorySystem"),
}


def _load_class(module_path: str, class_name: str):
    """Dynamically load a class from a module path."""
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)


async def cmd_run(args):
    """Run academic benchmarks."""
    from benchmarks.academic.harness.runner import AcademicBenchmarkRunner, save_result

    # Resolve benchmark
    if args.benchmark not in DATASET_REGISTRY:
        print(f"Unknown benchmark: {args.benchmark}")
        print(f"Available: {', '.join(DATASET_REGISTRY)}")
        sys.exit(1)

    # Resolve systems
    if args.all:
        system_ids = list(SYSTEM_REGISTRY.keys())
    else:
        system_ids = [s.strip() for s in args.systems.split(",")]
        for sid in system_ids:
            if sid not in SYSTEM_REGISTRY:
                print(f"Unknown system: {sid}")
                print(f"Available: {', '.join(SYSTEM_REGISTRY)}")
                sys.exit(1)

    seeds = [int(s) for s in args.seeds.split(",")]

    # Load dataset
    mod_path, cls_name = DATASET_REGISTRY[args.benchmark]
    dataset_cls = _load_class(mod_path, cls_name)
    dataset = dataset_cls()
    await dataset.load(args.data_dir)

    print(f"\nAcademic Benchmark: {args.benchmark}")
    print(f"Systems: {', '.join(system_ids)}")
    print(f"Seeds: {seeds}")
    print()

    # LLM config for answer generation
    llm_config = {}
    if args.llm_model:
        llm_config["model"] = args.llm_model
    if args.api_key:
        llm_config["api_key"] = args.api_key
    if args.base_url:
        llm_config["base_url"] = args.base_url

    results_dir = Path(args.results_dir) / args.benchmark
    results_dir.mkdir(parents=True, exist_ok=True)

    for system_id in system_ids:
        for seed in seeds:
            print(f"=== {system_id} (seed={seed}) on {args.benchmark} ===")

            try:
                mod_path, cls_name = SYSTEM_REGISTRY[system_id]
                system_cls = _load_class(mod_path, cls_name)
                system = system_cls()

                config = {"seed": seed}
                if args.llm_model:
                    config["llm_model"] = args.llm_model
                if args.api_key:
                    config["api_key"] = args.api_key
                await system.setup(config)

                # LLM-as-Judge config (optional)
                judge_config = None
                if args.judge_model:
                    judge_config = {"model": args.judge_model}
                    judge_key = args.judge_api_key or args.api_key
                    if judge_key:
                        judge_config["api_key"] = judge_key
                    if args.judge_base_url:
                        judge_config["base_url"] = args.judge_base_url

                runner = AcademicBenchmarkRunner(
                    dataset=dataset,
                    system=system,
                    llm_config=llm_config,
                    consolidation_interval=args.consolidation_interval,
                    judge_config=judge_config,
                )
                result = await runner.run(seed=seed)

                # Save result
                suffix = f"_seed{seed}" if len(seeds) > 1 else ""
                result_path = str(results_dir / f"{system_id}{suffix}.json")
                save_result(result, result_path)

                # Print summary
                print(f"  Scores: {result.aggregate_scores}")
                print(f"  LLM calls: {result.system_metrics.total_llm_calls}")
                print(f"  Latency (med): {result.system_metrics.median_query_latency_ms:.1f}ms")
                print()

                await system.teardown()

            except ImportError as e:
                print(f"  SKIPPED (missing dependency): {e}")
                print()
            except Exception as e:
                print(f"  ERROR: {e}")
                import traceback

                traceback.print_exc()
                print()


async def cmd_list(args):
    """List available benchmarks and systems."""
    print("Available benchmarks:")
    for bid in DATASET_REGISTRY:
        print(f"  {bid}")

    print("\nAvailable systems:")
    for sid in SYSTEM_REGISTRY:
        print(f"  {sid}")


async def cmd_report(args):
    """Generate a comparison report from results."""
    import json

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        sys.exit(1)

    # Collect all results
    all_results: list[dict] = []
    for json_file in sorted(results_dir.rglob("*.json")):
        data = json.loads(json_file.read_text())
        data["_file"] = str(json_file)
        all_results.append(data)

    if not all_results:
        print("No results found.")
        return

    # Group by benchmark
    by_benchmark: dict[str, list[dict]] = {}
    for r in all_results:
        bid = r.get("benchmark_id", "unknown")
        by_benchmark.setdefault(bid, []).append(r)

    # Print report
    for benchmark_id, results in sorted(by_benchmark.items()):
        print(f"\n{'=' * 60}")
        print(f"  {benchmark_id.upper()}")
        print(f"{'=' * 60}")

        # Header
        score_keys = set()
        for r in results:
            score_keys.update(r.get("aggregate_scores", {}).keys())
        score_keys = sorted(score_keys)

        header = f"{'System':<20}"
        for k in score_keys:
            header += f"  {k:<12}"
        header += f"  {'LLM Calls':<10}  {'Latency(ms)':<12}  {'Storage':<10}"
        print(header)
        print("-" * len(header))

        for r in sorted(results, key=lambda x: x.get("system_id", "")):
            sid = r.get("system_id", "?")
            scores = r.get("aggregate_scores", {})
            metrics = r.get("system_metrics", {})

            line = f"{sid:<20}"
            for k in score_keys:
                val = scores.get(k, 0.0)
                line += f"  {val:<12.3f}"

            llm_calls = metrics.get("total_llm_calls", 0)
            latency = metrics.get("median_query_latency_ms", 0.0)
            storage = metrics.get("storage_bytes", 0)

            line += f"  {llm_calls:<10}  {latency:<12.1f}  {storage:<10}"
            print(line)

        # Per-category breakdown
        print("\nPer-category breakdown:")
        for r in sorted(results, key=lambda x: x.get("system_id", "")):
            sid = r.get("system_id", "?")
            by_cat = r.get("scores_by_category", {})
            if by_cat:
                print(f"  {sid}:")
                for cat, scores in sorted(by_cat.items()):
                    primary = scores.get(
                        "f1", scores.get("accuracy", scores.get("task_completion", 0.0))
                    )
                    print(f"    {cat}: {primary:.3f}")


async def cmd_prepare_all(args):
    """Prepare every available academic benchmark for one system."""
    from benchmarks.academic.prepare import main_prepare

    if args.system not in SYSTEM_REGISTRY:
        print(f"Unknown system: {args.system}")
        print(f"Available: {', '.join(SYSTEM_REGISTRY)}")
        sys.exit(1)

    if args.benchmarks == "all":
        benchmark_ids = list(DATASET_REGISTRY.keys())
    else:
        benchmark_ids = [b.strip() for b in args.benchmarks.split(",") if b.strip()]

    unknown = [b for b in benchmark_ids if b not in DATASET_REGISTRY]
    if unknown:
        print(f"Unknown benchmark(s): {', '.join(unknown)}")
        print(f"Available: {', '.join(DATASET_REGISTRY)}")
        sys.exit(1)

    prepared: list[str] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []

    for benchmark_id in benchmark_ids:
        mod_path, cls_name = DATASET_REGISTRY[benchmark_id]
        dataset_cls = _load_class(mod_path, cls_name)
        dataset = dataset_cls()

        print(f"\n{'=' * 60}")
        print(f"  PREPARE CHECK: {benchmark_id}")
        print(f"{'=' * 60}", flush=True)

        try:
            await dataset.load(args.data_dir)
        except FileNotFoundError as e:
            msg = str(e)
            skipped.append((benchmark_id, msg))
            print(f"SKIPPED: {benchmark_id}\n{msg}", flush=True)
            if not args.skip_missing:
                break
            continue
        except Exception as e:  # dataset adapter bug or unsupported format
            msg = f"{type(e).__name__}: {e}"
            failed.append((benchmark_id, msg))
            print(f"FAILED while loading {benchmark_id}: {msg}", flush=True)
            if not args.skip_missing:
                break
            continue

        prep_args = SimpleNamespace(
            benchmark=benchmark_id,
            system=args.system,
            workers=args.workers,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            llm_model=args.llm_model,
            api_key=args.api_key,
            base_url=args.base_url,
            resume=args.resume,
        )

        try:
            await main_prepare(prep_args)
            prepared.append(benchmark_id)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            failed.append((benchmark_id, msg))
            print(f"FAILED while preparing {benchmark_id}: {msg}", flush=True)
            if not args.skip_missing:
                break

    print(f"\n{'=' * 60}")
    print("  PREPARE-ALL SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Prepared: {', '.join(prepared) if prepared else '(none)'}")
    print(f"  Skipped:  {', '.join(b for b, _ in skipped) if skipped else '(none)'}")
    print(f"  Failed:   {', '.join(b for b, _ in failed) if failed else '(none)'}")
    if skipped:
        print("\n  Skipped details:")
        for benchmark_id, msg in skipped:
            first_line = msg.splitlines()[0] if msg else ""
            print(f"    {benchmark_id}: {first_line}")
    if failed:
        print("\n  Failed details:")
        for benchmark_id, msg in failed:
            print(f"    {benchmark_id}: {msg}")


def main():
    parser = argparse.ArgumentParser(
        prog="benchmarks.academic",
        description="Academic benchmark suite for alive-memory",
    )
    sub = parser.add_subparsers(dest="command")

    # --- run ---
    run_p = sub.add_parser("run", help="Run academic benchmarks")
    run_p.add_argument(
        "--benchmark", required=True, choices=list(DATASET_REGISTRY.keys()), help="Benchmark to run"
    )
    run_p.add_argument("--systems", default="alive,rag", help="Comma-separated system IDs")
    run_p.add_argument("--all", action="store_true", help="Run all systems")
    run_p.add_argument("--seeds", default="42", help="Comma-separated seeds")
    run_p.add_argument("--llm-model", default=None, help="LLM model for answer generation")
    run_p.add_argument("--api-key", default=None, help="API key for LLM provider")
    run_p.add_argument(
        "--base-url", default=None, help="Base URL for LLM API (e.g. https://openrouter.ai/api/v1)"
    )
    run_p.add_argument(
        "--data-dir",
        default="benchmarks/academic/data",
        help="Directory containing benchmark datasets",
    )
    run_p.add_argument(
        "--results-dir", default="benchmarks/academic/results", help="Directory to save results"
    )
    run_p.add_argument(
        "--consolidation-interval",
        type=int,
        default=10,
        help="Sessions between consolidation calls",
    )
    run_p.add_argument(
        "--judge-model",
        default=None,
        help="LLM model for LLM-as-Judge scoring (enables judge metric)",
    )
    run_p.add_argument(
        "--judge-api-key", default=None, help="API key for judge LLM (defaults to --api-key)"
    )
    run_p.add_argument(
        "--judge-base-url", default=None, help="Base URL for judge LLM (defaults to OpenRouter)"
    )

    # --- list ---
    sub.add_parser("list", help="List available benchmarks and systems")

    # --- report ---
    rep_p = sub.add_parser("report", help="Generate report from results")
    rep_p.add_argument("--results-dir", default="benchmarks/academic/results")

    # --- prepare ---
    prep_p = sub.add_parser("prepare", help="Prepare: ingest + consolidate + save state")
    prep_p.add_argument("--benchmark", required=True, choices=list(DATASET_REGISTRY.keys()))
    prep_p.add_argument("--system", default="alive")
    prep_p.add_argument("--workers", type=int, default=16)
    prep_p.add_argument("--data-dir", default="benchmarks/academic/data")
    prep_p.add_argument("--output-dir", default="benchmarks/academic/prepared")
    prep_p.add_argument("--llm-model", default=None)
    prep_p.add_argument("--api-key", default=None)
    prep_p.add_argument("--base-url", default=None)
    prep_p.add_argument("--resume", action="store_true", help="Skip already-prepared instances")

    # --- prepare-all ---
    prep_all_p = sub.add_parser("prepare-all", help="Prepare every available academic benchmark")
    prep_all_p.add_argument(
        "--benchmarks", default="all", help="Comma-separated benchmarks or 'all'"
    )
    prep_all_p.add_argument("--system", default="alive")
    prep_all_p.add_argument("--workers", type=int, default=4)
    prep_all_p.add_argument("--data-dir", default="benchmarks/academic/data")
    prep_all_p.add_argument("--output-dir", default="benchmarks/academic/prepared")
    prep_all_p.add_argument("--llm-model", default=None)
    prep_all_p.add_argument("--api-key", default=None)
    prep_all_p.add_argument("--base-url", default=None)
    prep_all_p.add_argument("--resume", action="store_true", help="Skip already-prepared instances")
    prep_all_p.add_argument(
        "--skip-missing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip benchmarks whose datasets are missing",
    )

    # --- bench ---
    bench_p = sub.add_parser("bench", help="Bench: load prepared state + run queries")
    bench_p.add_argument("--benchmark", required=True, choices=list(DATASET_REGISTRY.keys()))
    bench_p.add_argument("--prepared-dir", required=True, help="Directory with prepared instances")
    bench_p.add_argument("--workers", type=int, default=16)
    bench_p.add_argument("--data-dir", default="benchmarks/academic/data")
    bench_p.add_argument("--results-dir", default="benchmarks/academic/results")
    bench_p.add_argument("--llm-model", default=None)
    bench_p.add_argument("--api-key", default=None)
    bench_p.add_argument(
        "--base-url", default=None, help="Base URL for LLM API (e.g. https://openrouter.ai/api/v1)"
    )
    bench_p.add_argument("--resume", action="store_true", help="Skip already-answered instances")
    bench_p.add_argument("--judge-model", default=None)
    bench_p.add_argument("--judge-api-key", default=None)
    bench_p.add_argument("--judge-base-url", default=None)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "list":
        asyncio.run(cmd_list(args))
    elif args.command == "report":
        asyncio.run(cmd_report(args))
    elif args.command == "prepare":
        from benchmarks.academic.prepare import main_prepare

        asyncio.run(main_prepare(args))
    elif args.command == "prepare-all":
        asyncio.run(cmd_prepare_all(args))
    elif args.command == "bench":
        from benchmarks.academic.bench import main_bench

        asyncio.run(main_bench(args))


if __name__ == "__main__":
    main()
