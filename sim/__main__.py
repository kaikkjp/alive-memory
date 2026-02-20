"""sim.__main__ — CLI entry point for simulation experiments.

Usage:
    python -m sim --variant full --scenario standard --cycles 1000 --llm mock
    python -m sim --experiment baselines --llm mock --cycles 100
    python -m sim --experiment ablation --llm mock --cycles 100
    python -m sim --experiment stress --llm mock
    python -m sim --compare sim/results/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m sim",
        description="ALIVE Research Simulation Framework",
    )

    parser.add_argument(
        "--variant", type=str, default="full",
        help="Pipeline variant: full, stateless, react, no_drives, "
             "no_sleep, no_affect, no_basal_ganglia, no_memory",
    )
    parser.add_argument(
        "--scenario", type=str, default="standard",
        help="Scenario: standard, longitudinal, death_spiral, "
             "visitor_flood, isolation, spam_attack, sleep_deprivation",
    )
    parser.add_argument(
        "--cycles", type=int, default=1000,
        help="Number of cycles to run (default: 1000)",
    )
    parser.add_argument(
        "--llm", type=str, default="mock",
        choices=["mock", "cached"],
        help="LLM mode: mock (free, deterministic) or cached (real with cache)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="sim/results",
        help="Output directory for results (default: sim/results)",
    )
    parser.add_argument(
        "--experiment", type=str, default=None,
        choices=["baselines", "ablation", "stress", "longitudinal"],
        help="Run a predefined experiment batch",
    )
    parser.add_argument(
        "--compare", type=str, default=None,
        help="Compare results from a directory and export tables",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print progress every 100 cycles",
    )

    return parser.parse_args()


async def run_single(args) -> dict:
    """Run a single simulation."""
    from sim.runner import SimulationRunner
    from sim.metrics.collector import SimMetricsCollector

    print(f"[Sim] Running: variant={args.variant} scenario={args.scenario} "
          f"cycles={args.cycles} llm={args.llm} seed={args.seed}")

    runner = SimulationRunner(
        variant=args.variant,
        scenario=args.scenario,
        num_cycles=args.cycles,
        llm_mode=args.llm,
        seed=args.seed,
        output_dir=args.output_dir,
        verbose=args.verbose,
    )

    t0 = time.time()
    result = await runner.run()
    elapsed = time.time() - t0

    # Collect metrics
    collector = SimMetricsCollector()
    for cycle in result.cycles:
        collector.record_cycle(cycle.cycle_num, cycle)
    metrics = collector.compute_all()

    # Export
    output_path = await runner.export(result)

    print(f"[Sim] Done in {elapsed:.1f}s")
    print(f"[Sim] Cycles: {metrics['m1_uptime']}")
    print(f"[Sim] Initiative: {metrics['m2_initiative_rate']}%")
    print(f"[Sim] Entropy: {metrics['m3_entropy']}")
    print(f"[Sim] Knowledge: {metrics['m4_knowledge']}")
    print(f"[Sim] Emotional range: {metrics['m7_emotional_range']}")
    print(f"[Sim] Results: {output_path}")

    return {
        "variant": args.variant,
        "result": result.to_dict(),
        "metrics": metrics,
    }


async def run_experiment(args):
    """Run a predefined experiment batch."""
    from sim.runner import SimulationRunner
    from sim.metrics.collector import SimMetricsCollector
    from sim.metrics.comparator import MetricsComparator

    all_metrics = {}

    if args.experiment == "baselines":
        variants = ["full", "stateless", "react"]
        scenario = "standard"
    elif args.experiment == "ablation":
        variants = ["full", "no_drives", "no_sleep", "no_affect",
                     "no_basal_ganglia", "no_memory"]
        scenario = "standard"
    elif args.experiment == "stress":
        # Run full ALIVE against all stress scenarios
        scenarios = ["death_spiral", "visitor_flood", "isolation",
                     "spam_attack", "sleep_deprivation"]
        for sc in scenarios:
            print(f"\n{'='*60}")
            print(f"[Experiment] Stress: {sc}")
            print(f"{'='*60}")

            cycles = 500
            runner = SimulationRunner(
                variant="full", scenario=sc,
                num_cycles=cycles, llm_mode=args.llm,
                seed=args.seed, output_dir=args.output_dir,
                verbose=args.verbose,
            )
            t0 = time.time()
            result = await runner.run()
            elapsed = time.time() - t0

            collector = SimMetricsCollector()
            for cycle in result.cycles:
                collector.record_cycle(cycle.cycle_num, cycle)
            metrics = collector.compute_all()

            all_metrics[sc] = metrics
            await runner.export(result)

            print(f"[Stress:{sc}] Done in {elapsed:.1f}s — "
                  f"valence range: {metrics['m7_emotional_range']}")

        # Export comparison
        comparator = MetricsComparator(all_metrics)
        comparator.export_csv(args.output_dir)
        comparator.export_json(args.output_dir)
        print(f"\n[Experiment] Stress tests complete. "
              f"Results in {args.output_dir}/")
        return

    elif args.experiment == "longitudinal":
        print(f"\n{'='*60}")
        print(f"[Experiment] Longitudinal (10,000 cycles)")
        print(f"{'='*60}")

        runner = SimulationRunner(
            variant="full", scenario="longitudinal",
            num_cycles=10000, llm_mode=args.llm,
            seed=args.seed, output_dir=args.output_dir,
            verbose=True,
        )
        t0 = time.time()
        result = await runner.run()
        elapsed = time.time() - t0

        collector = SimMetricsCollector()
        for cycle in result.cycles:
            collector.record_cycle(cycle.cycle_num, cycle)
        metrics = collector.compute_all()

        await runner.export(result)

        print(f"[Longitudinal] Done in {elapsed:.1f}s")
        print(f"[Longitudinal] Initiative: {metrics['m2_initiative_rate']}%")
        print(f"[Longitudinal] Knowledge: {metrics['m4_knowledge']}")
        print(f"[Longitudinal] Emotional range: {metrics['m7_emotional_range']}")
        return

    else:
        print(f"Unknown experiment: {args.experiment}")
        return

    # Run variants (baselines or ablation)
    for variant in variants:
        print(f"\n{'='*60}")
        print(f"[Experiment] {args.experiment}: {variant}")
        print(f"{'='*60}")

        runner = SimulationRunner(
            variant=variant, scenario=scenario,
            num_cycles=args.cycles, llm_mode=args.llm,
            seed=args.seed, output_dir=args.output_dir,
            verbose=args.verbose,
        )
        t0 = time.time()
        result = await runner.run()
        elapsed = time.time() - t0

        collector = SimMetricsCollector()
        for cycle in result.cycles:
            collector.record_cycle(cycle.cycle_num, cycle)
        metrics = collector.compute_all()

        all_metrics[variant] = metrics
        await runner.export(result)

        print(f"[{variant}] Done in {elapsed:.1f}s — "
              f"initiative={metrics['m2_initiative_rate']}% "
              f"entropy={metrics['m3_entropy']}")

    # Compare and export
    comparator = MetricsComparator(all_metrics)
    comparator.export_csv(args.output_dir)
    comparator.export_json(args.output_dir)

    print(f"\n[Experiment] {args.experiment} complete.")
    print(f"[Experiment] Results in {args.output_dir}/")

    # Print summary table
    print(f"\n{'System':<20} {'Initiative':>10} {'Entropy':>8} "
          f"{'Knowledge':>10} {'EmRange':>8}")
    print("-" * 60)
    for variant, m in all_metrics.items():
        print(f"{variant:<20} {m['m2_initiative_rate']:>9.1f}% "
              f"{m['m3_entropy']:>8.3f} {m['m4_knowledge']:>10d} "
              f"{m['m7_emotional_range']:>8.3f}")


def do_compare(results_dir: str):
    """Compare existing results and export tables."""
    from sim.metrics.comparator import MetricsComparator

    comparator = MetricsComparator.from_results_dir(results_dir)
    comparator.export_csv(results_dir)
    comparator.export_json(results_dir)

    table = comparator.comparison_table()
    if table:
        print(f"\nComparison ({len(table)} systems):")
        for row in table:
            print(f"  {row}")
    print(f"\nExported to {results_dir}/")


def main():
    args = parse_args()

    if args.compare:
        do_compare(args.compare)
        return

    if args.experiment:
        asyncio.run(run_experiment(args))
    else:
        asyncio.run(run_single(args))


if __name__ == "__main__":
    main()
