"""CLI entry point for the benchmark framework.

Usage:
    python -m benchmarks.run --stream research_assistant_10k --all
    python -m benchmarks.run --stream research_assistant_10k --systems alive,rag
    python -m benchmarks.run --stream research_assistant_10k --systems alive --max-cycles 1000
    python -m benchmarks.generate --scenario research_assistant --seed 42
    python -m benchmarks.report --results-dir benchmarks/results/
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ADAPTER_REGISTRY = {
    "rag": ("benchmarks.adapters.chroma_rag", "ChromaRagAdapter"),
    "rag+": ("benchmarks.adapters.chroma_rag_plus", "ChromaRagPlusAdapter"),
    "alive": ("benchmarks.adapters.alive_adapter", "AliveMemoryAdapter"),
    "lcb": ("benchmarks.adapters.langchain_buffer", "LangChainBufferAdapter"),
    "lcs": ("benchmarks.adapters.langchain_summary", "LangChainSummaryAdapter"),
    "mem0": ("benchmarks.adapters.mem0_adapter", "Mem0Adapter"),
    "zep": ("benchmarks.adapters.zep_adapter", "ZepAdapter"),
}


def _load_adapter(system_id: str):
    """Dynamically load an adapter class."""
    if system_id not in ADAPTER_REGISTRY:
        print(f"Unknown system: {system_id}")
        print(f"Available: {', '.join(ADAPTER_REGISTRY)}")
        sys.exit(1)

    module_path, class_name = ADAPTER_REGISTRY[system_id]
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


def _resolve_stream_paths(stream_name: str, data_dir: str) -> dict[str, str]:
    """Resolve stream name to file paths."""
    base = Path(data_dir)

    # Try exact name first
    stream_file = base / "streams" / f"{stream_name}.jsonl"
    if not stream_file.exists():
        # Try with common suffixes
        for suffix in ["_10k", "_5k", "_15k", "_50k"]:
            candidate = base / "streams" / f"{stream_name}{suffix}.jsonl"
            if candidate.exists():
                stream_file = candidate
                break

    if not stream_file.exists():
        print(f"Stream not found: {stream_file}")
        print(f"Available streams:")
        streams_dir = base / "streams"
        if streams_dir.exists():
            for f in sorted(streams_dir.glob("*.jsonl")):
                print(f"  {f.stem}")
        else:
            print(f"  (no streams directory at {streams_dir})")
            print(f"  Run: python -m benchmarks.generate --scenario research_assistant")
        sys.exit(1)

    # Derive query and ground truth paths from stream name
    # Strip the _Nk suffix to get the base scenario name
    scenario = stream_file.stem
    for suffix in ["_10k", "_5k", "_15k", "_50k", "_1k"]:
        if scenario.endswith(suffix):
            scenario = scenario[: -len(suffix)]
            break

    query_file = base / "queries" / f"{scenario}_queries.jsonl"
    gt_file = base / "ground_truth" / f"{scenario}_gt.jsonl"

    if not query_file.exists():
        print(f"Query file not found: {query_file}")
        print("Generate data first: python -m benchmarks.generate")
        sys.exit(1)

    if not gt_file.exists():
        print(f"Ground truth not found: {gt_file}")
        print("Generate data first: python -m benchmarks.generate")
        sys.exit(1)

    return {
        "stream": str(stream_file),
        "queries": str(query_file),
        "ground_truth": str(gt_file),
    }


def _detect_primary_users(stream_path: str) -> list[str]:
    """Detect primary users from stream metadata."""
    from benchmarks.runner import load_jsonl

    events = load_jsonl(stream_path)
    user_counts: dict[str, int] = {}
    for e in events[:2000]:  # Sample first 2000 events
        source = e.get("metadata", {}).get("source", "")
        if source and source != "system":
            user_counts[source] = user_counts.get(source, 0) + 1

    # Top 3 users by frequency are "primary"
    sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    return [u for u, _ in sorted_users[:3]]


async def cmd_run(args):
    """Run benchmarks."""
    from benchmarks.runner import BenchmarkRunner

    paths = _resolve_stream_paths(args.stream, args.data_dir)

    # Determine systems to run
    if args.all:
        systems = list(ADAPTER_REGISTRY.keys())
    else:
        systems = [s.strip() for s in args.systems.split(",")]

    seeds = [int(s) for s in args.seeds.split(",")]

    # Detect primary users for entity confusion scoring
    primary_users = _detect_primary_users(paths["stream"])

    print(f"Benchmark: {args.stream}")
    print(f"Systems: {', '.join(systems)}")
    print(f"Seeds: {seeds}")
    if args.max_cycles:
        print(f"Max cycles: {args.max_cycles}")
    if primary_users:
        print(f"Primary users: {', '.join(primary_users)}")
    print()

    results_dir = Path(args.results_dir) / args.stream
    results_dir.mkdir(parents=True, exist_ok=True)

    for system_id in systems:
        for seed in seeds:
            print(f"=== Running {system_id} (seed={seed}) ===")

            try:
                adapter = _load_adapter(system_id)
                runner = BenchmarkRunner(
                    stream_path=paths["stream"],
                    query_path=paths["queries"],
                    ground_truth_path=paths["ground_truth"],
                    consolidation_interval=args.consolidation_interval,
                    max_cycles=args.max_cycles,
                    primary_users=primary_users,
                )
                result = await runner.run(
                    adapter,
                    system_id=system_id,
                    seed=seed,
                    stream_name=args.stream,
                )

                # Save result
                suffix = f"_seed{seed}" if len(seeds) > 1 else ""
                result_path = str(results_dir / f"{system_id}{suffix}.json")
                result.save(result_path)
                print(
                    f"  Done: {result.total_events} events in "
                    f"{result.wall_time_seconds:.1f}s → {result_path}"
                )
            except ImportError as e:
                print(f"  SKIPPED (missing dependency): {e}")
            except Exception as e:
                print(f"  ERROR: {e}")
                import traceback
                traceback.print_exc()

            print()


async def cmd_generate(args):
    """Generate benchmark data."""
    from benchmarks.generate_streams import StreamGenerator, generate_stress_test

    if args.scenario == "stress_test":
        paths = generate_stress_test(
            args.output_dir,
            seed=args.seed,
            total_events=args.events or 50_000,
        )
    else:
        gen = StreamGenerator(
            scenario=args.scenario,
            total_events=args.events,
            seed=args.seed,
            noise_ratio=args.noise_ratio,
        )
        paths = gen.generate(args.output_dir)


async def cmd_cross_domain(args):
    """Run cross-domain transfer test."""
    from benchmarks.cross_domain import CrossDomainRunner

    train_paths = _resolve_stream_paths(args.train, args.data_dir)
    test_paths = _resolve_stream_paths(args.test, args.data_dir)

    if args.all:
        systems = list(ADAPTER_REGISTRY.keys())
    else:
        systems = [s.strip() for s in args.systems.split(",")]

    print(f"Cross-domain: train={args.train}, test={args.test}")
    print(f"Systems: {', '.join(systems)}")
    print()

    results_dir = Path(args.results_dir) / f"cross_domain_{args.train}_to_{args.test}"
    results_dir.mkdir(parents=True, exist_ok=True)

    for system_id in systems:
        print(f"=== Running {system_id} ===")
        try:
            adapter = _load_adapter(system_id)
            runner = CrossDomainRunner(
                train_stream_path=train_paths["stream"],
                test_query_path=test_paths["queries"],
                test_gt_path=test_paths["ground_truth"],
                max_cycles=args.max_cycles,
                consolidation_interval=args.consolidation_interval,
            )
            result = await runner.run(
                adapter,
                system_id=system_id,
                train_stream=args.train,
                test_stream=args.test,
            )
            result_path = str(results_dir / f"{system_id}.json")
            result.save(result_path)
            print(f"  Transfer F1: {result.transfer_f1:.3f}, "
                  f"Interference: {result.interference_rate:.3f} → {result_path}")
        except ImportError as e:
            print(f"  SKIPPED (missing dependency): {e}")
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
        print()


async def cmd_stress(args):
    """Run concurrent stress test."""
    from benchmarks.concurrent_runner import ConcurrentRunner

    paths = _resolve_stream_paths(args.stream, args.data_dir)

    if args.all:
        systems = list(ADAPTER_REGISTRY.keys())
    else:
        systems = [s.strip() for s in args.systems.split(",")]

    print(f"Stress test: concurrency={args.concurrency}")
    print(f"Systems: {', '.join(systems)}")
    print()

    results_dir = Path(args.results_dir) / f"stress_c{args.concurrency}"
    results_dir.mkdir(parents=True, exist_ok=True)

    for system_id in systems:
        print(f"=== Running {system_id} (concurrency={args.concurrency}) ===")
        try:
            adapter = _load_adapter(system_id)
            runner = ConcurrentRunner(
                stream_path=paths["stream"],
                concurrency=args.concurrency,
                max_cycles=args.max_cycles,
            )
            result = await runner.run(adapter, system_id=system_id)
            result_path = str(results_dir / f"{system_id}.json")
            result.save(result_path)
            print(f"  Throughput: {result.throughput:.1f} ops/s, "
                  f"p99: {result.p99_ms:.1f}ms, "
                  f"degradation: {result.degradation_ratio:.2f}x → {result_path}")
        except ImportError as e:
            print(f"  SKIPPED (missing dependency): {e}")
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
        print()


async def cmd_report(args):
    """Generate report from results."""
    from benchmarks.report import ReportGenerator

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        sys.exit(1)

    generator = ReportGenerator(str(results_dir))
    generator.generate_markdown(args.output or str(results_dir / "report.md"))

    if args.charts:
        charts_dir = str(results_dir / "charts")
        generator.generate_charts(charts_dir)
        print(f"Charts saved to {charts_dir}/")


def main():
    parser = argparse.ArgumentParser(
        prog="benchmarks",
        description="alive-memory benchmark framework",
    )
    sub = parser.add_subparsers(dest="command")

    # --- run ---
    run_p = sub.add_parser("run", help="Run benchmarks")
    run_p.add_argument("--stream", required=True, help="Stream name (e.g., research_assistant_10k)")
    run_p.add_argument("--systems", default="alive,rag", help="Comma-separated system IDs")
    run_p.add_argument("--all", action="store_true", help="Run all systems")
    run_p.add_argument("--seeds", default="42", help="Comma-separated seeds")
    run_p.add_argument("--max-cycles", type=int, default=None, help="Limit event count")
    run_p.add_argument("--consolidation-interval", type=int, default=500)
    run_p.add_argument("--data-dir", default="benchmarks/data")
    run_p.add_argument("--results-dir", default="benchmarks/results")

    # --- generate ---
    gen_p = sub.add_parser("generate", help="Generate benchmark data")
    gen_p.add_argument("--scenario", default="research_assistant",
                       choices=["research_assistant", "customer_support",
                                "personal_assistant", "stress_test"])
    gen_p.add_argument("--seed", type=int, default=42)
    gen_p.add_argument("--events", type=int, default=None)
    gen_p.add_argument("--noise-ratio", type=float, default=0.0)
    gen_p.add_argument("--output-dir", default="benchmarks/data")

    # --- report ---
    rep_p = sub.add_parser("report", help="Generate report from results")
    rep_p.add_argument("--results-dir", default="benchmarks/results")
    rep_p.add_argument("--output", default=None)
    rep_p.add_argument("--charts", action="store_true")

    # --- cross-domain ---
    cd_p = sub.add_parser("cross-domain", help="Run cross-domain transfer test")
    cd_p.add_argument("--train", required=True, help="Training domain stream name")
    cd_p.add_argument("--test", required=True, help="Test domain stream name")
    cd_p.add_argument("--systems", default="alive,rag", help="Comma-separated system IDs")
    cd_p.add_argument("--all", action="store_true", help="Run all systems")
    cd_p.add_argument("--max-cycles", type=int, default=None)
    cd_p.add_argument("--consolidation-interval", type=int, default=500)
    cd_p.add_argument("--data-dir", default="benchmarks/data")
    cd_p.add_argument("--results-dir", default="benchmarks/results")

    # --- stress (concurrent) ---
    stress_p = sub.add_parser("stress", help="Run concurrent stress test")
    stress_p.add_argument("--stream", default="research_assistant_10k", help="Stream name")
    stress_p.add_argument("--systems", default="alive,rag", help="Comma-separated system IDs")
    stress_p.add_argument("--all", action="store_true", help="Run all systems")
    stress_p.add_argument("--concurrency", type=int, default=10, help="Parallel operations")
    stress_p.add_argument("--max-cycles", type=int, default=None)
    stress_p.add_argument("--data-dir", default="benchmarks/data")
    stress_p.add_argument("--results-dir", default="benchmarks/results")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "generate":
        asyncio.run(cmd_generate(args))
    elif args.command == "report":
        asyncio.run(cmd_report(args))
    elif args.command == "cross-domain":
        asyncio.run(cmd_cross_domain(args))
    elif args.command == "stress":
        asyncio.run(cmd_stress(args))


if __name__ == "__main__":
    main()
