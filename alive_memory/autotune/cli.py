"""CLI entry point for alive-memory autotune."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging


async def _run(args: argparse.Namespace) -> None:
    from alive_memory.autotune.engine import autotune
    from alive_memory.autotune.report import generate_report
    from alive_memory.autotune.types import AutotuneConfig
    from alive_memory.config import AliveConfig

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    base_config = AliveConfig(args.config) if args.config else AliveConfig()

    at_config = AutotuneConfig(
        budget=args.budget,
        scenarios=args.scenarios,
        seed=args.seed,
        verbose=True,
    )

    result = await autotune(config=base_config, autotune_config=at_config)

    # Write result JSON
    with open(args.output, "w") as f:
        json.dump(
            {
                "best_config": result.best_config,
                "baseline_composite": result.baseline_composite,
                "best_composite": result.best_composite,
                "improvement_pct": result.improvement_pct,
                "total_iterations": result.total_iterations,
                "elapsed_seconds": result.elapsed_seconds,
            },
            f,
            indent=2,
        )
    print(f"Result saved to {args.output}")

    # Write report
    report = generate_report(result)
    with open(args.report, "w") as f:
        f.write(report)
    print(f"Report saved to {args.report}")

    print(f"\nImprovement: {result.improvement_pct:.1f}%")
    print(f"Best composite: {result.best_composite:.4f} (baseline: {result.baseline_composite:.4f})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-tune alive-memory parameters"
    )
    parser.add_argument("--budget", type=int, default=50, help="Number of iterations")
    parser.add_argument("--scenarios", default="builtin", help="Scenario source")
    parser.add_argument("--output", default="autotune_result.json", help="Output JSON path")
    parser.add_argument("--report", default="autotune_report.md", help="Report path")
    parser.add_argument("--config", help="Path to base config YAML")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
