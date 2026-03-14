"""CLI entry point for alive-memory evolve."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging


async def _run(args: argparse.Namespace) -> None:
    from tools.evolve import evolve
    from tools.evolve.report import generate_report
    from tools.evolve.types import EvolveConfig

    logging.basicConfig(
        level=logging.INFO if not args.quiet else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    evolve_config = EvolveConfig(
        budget=args.budget,
        eval_suite_path=args.suite or "",
        target_files=args.target_files.split(",") if args.target_files else [],
        verbose=not args.quiet,
    )

    llm = _create_llm(args.llm)
    result = await evolve(evolve_config=evolve_config, llm_fn=llm)

    # Write result JSON
    with open(args.output, "w") as f:
        json.dump(
            {
                "baseline_composite": result.baseline_score.composite if result.baseline_score else None,
                "best_composite": result.best_score.composite if result.best_score else None,
                "improvement_pct": _improvement_pct(result),
                "total_iterations": result.total_iterations,
                "promoted_count": sum(1 for i in result.iterations if i.promoted),
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

    # Print summary
    if result.best_score and result.baseline_score:
        imp = _improvement_pct(result)
        print(f"\nImprovement: {imp:.1f}%")
        print(
            f"Best composite: {result.best_score.composite:.4f} "
            f"(baseline: {result.baseline_score.composite:.4f})"
        )
    else:
        print("\nNo improvement found.")


def _improvement_pct(result) -> float:
    """Calculate improvement percentage (positive = better)."""
    if result.baseline_score and result.best_score:
        baseline = result.baseline_score.composite
        best = result.best_score.composite
        if baseline > 0:
            return (baseline - best) / baseline * 100
    return 0.0


def _create_llm(provider: str | None):
    """Create an LLM provider instance.

    Supports ``"anthropic"`` and ``"openrouter"``.  When *provider* is ``None``,
    defaults to ``"anthropic"``.

    Returns:
        An :class:`~alive_memory.llm.provider.LLMProvider` implementation.
    """
    provider = (provider or "anthropic").lower()

    if provider == "anthropic":
        from alive_memory.llm.anthropic import AnthropicProvider

        return AnthropicProvider()

    if provider == "openrouter":
        from alive_memory.llm.openrouter import OpenRouterProvider

        return OpenRouterProvider()

    raise ValueError(f"Unknown LLM provider: {provider!r}. Use 'anthropic' or 'openrouter'.")


def main() -> None:
    """CLI entry point for ``alive-memory-evolve``."""
    parser = argparse.ArgumentParser(
        description="Evolve alive-memory algorithms using AI-guided code modification",
    )
    parser.add_argument("--budget", type=int, default=10, help="Number of iterations")
    parser.add_argument("--suite", help="Path to eval suite directory")
    parser.add_argument("--target-files", help="Comma-separated list of files to modify")
    parser.add_argument("--llm", help="LLM provider (anthropic, openrouter)")
    parser.add_argument("--output", default="evolve_result.json", help="Output JSON path")
    parser.add_argument("--report", default="evolve_report.md", help="Report path")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")

    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
