"""CLI entry point for the academic benchmark suite.

Usage:
    python -m benchmarks.academic run --benchmark locomo --systems alive,rag
    python -m benchmarks.academic run --benchmark longmemeval --all
    python -m benchmarks.academic run --benchmark locomo --all --judge-model anthropic/claude-haiku-4-5
    python -m benchmarks.academic list
    python -m benchmarks.academic report --results-dir benchmarks/academic/results/
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

DATASET_REGISTRY = {
    "locomo": ("benchmarks.academic.datasets.locomo", "LoCoMoDataset"),
    "longmemeval": ("benchmarks.academic.datasets.longmemeval", "LongMemEvalDataset"),
    "memoryagentbench": ("benchmarks.academic.datasets.memoryagentbench", "MemoryAgentBenchDataset"),
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
                    primary = scores.get("f1", scores.get("accuracy", scores.get("task_completion", 0.0)))
                    print(f"    {cat}: {primary:.3f}")


def main():
    parser = argparse.ArgumentParser(
        prog="benchmarks.academic",
        description="Academic benchmark suite for alive-memory",
    )
    sub = parser.add_subparsers(dest="command")

    # --- run ---
    run_p = sub.add_parser("run", help="Run academic benchmarks")
    run_p.add_argument("--benchmark", required=True,
                       choices=list(DATASET_REGISTRY.keys()),
                       help="Benchmark to run")
    run_p.add_argument("--systems", default="alive,rag",
                       help="Comma-separated system IDs")
    run_p.add_argument("--all", action="store_true",
                       help="Run all systems")
    run_p.add_argument("--seeds", default="42",
                       help="Comma-separated seeds")
    run_p.add_argument("--llm-model", default=None,
                       help="LLM model for answer generation")
    run_p.add_argument("--api-key", default=None,
                       help="API key for LLM provider")
    run_p.add_argument("--data-dir", default="benchmarks/academic/data",
                       help="Directory containing benchmark datasets")
    run_p.add_argument("--results-dir", default="benchmarks/academic/results",
                       help="Directory to save results")
    run_p.add_argument("--consolidation-interval", type=int, default=10,
                       help="Sessions between consolidation calls")
    run_p.add_argument("--judge-model", default=None,
                       help="LLM model for LLM-as-Judge scoring (enables judge metric)")
    run_p.add_argument("--judge-api-key", default=None,
                       help="API key for judge LLM (defaults to --api-key)")
    run_p.add_argument("--judge-base-url", default=None,
                       help="Base URL for judge LLM (defaults to OpenRouter)")

    # --- list ---
    sub.add_parser("list", help="List available benchmarks and systems")

    # --- report ---
    rep_p = sub.add_parser("report", help="Generate report from results")
    rep_p.add_argument("--results-dir", default="benchmarks/academic/results")

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


if __name__ == "__main__":
    main()
