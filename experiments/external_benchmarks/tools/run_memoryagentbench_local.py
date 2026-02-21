#!/usr/bin/env python3
"""Run MemoryAgentBench local smoke with SSL/NLTK bootstrap and stable data staging."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path

import nltk
import yaml

from common_metadata import assert_expected_model, make_metadata, normalize_model_name


# NLTK SSL workaround for environments with broken cert chain.
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context


def bootstrap_nltk() -> dict[str, bool]:
    return {
        "punkt": bool(nltk.download("punkt", quiet=True)),
        "punkt_tab": bool(nltk.download("punkt_tab", quiet=True)),
    }


def stage_local_dataset(
    bench_root: Path,
    local_data_dir: Path,
    sub_dataset: str,
    enforce_mechanism_contract: bool,
) -> dict[str, str]:
    dst_dir = bench_root / "raw_dataset" / "new_processed_data" / sub_dataset
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_pairs = local_data_dir / f"{sub_dataset}_pairs.json"
    src_context = local_data_dir / f"{sub_dataset}_context.txt"
    if not src_pairs.exists() or not src_context.exists():
        raise FileNotFoundError(
            f"Missing local smoke files under {local_data_dir}: "
            f"expected {src_pairs.name} and {src_context.name}"
        )

    dst_pairs = dst_dir / src_pairs.name
    dst_context = dst_dir / src_context.name
    if enforce_mechanism_contract:
        with src_pairs.open("r", encoding="utf-8") as f:
            qa_items = json.load(f)
        contract = (
            "Output format (MUST):\n"
            "1. MECHANISM: <one short phrase only>\n"
            "2. ANSWER: <optional 1-3 sentences>\n"
            "Constraints:\n"
            "- Mechanism line must be <= 8 words, hyphen allowed.\n"
            "- Do not include extra text on the MECHANISM line.\n"
            "- If your draft violates format, regenerate once before final answer.\n\n"
        )
        for item in qa_items:
            q = str(item.get("question", "")).strip()
            item["question"] = f"{contract}{q}"
        with dst_pairs.open("w", encoding="utf-8") as f:
            json.dump(qa_items, f, indent=2, ensure_ascii=False)
    else:
        shutil.copy2(src_pairs, dst_pairs)
    shutil.copy2(src_context, dst_context)

    return {
        "pairs": str(dst_pairs),
        "context": str(dst_context),
    }


def find_latest_output_json(bench_root: Path, start_ts: float) -> str | None:
    outputs_root = bench_root / "outputs"
    if not outputs_root.exists():
        return None

    candidates = sorted(
        (p for p in outputs_root.rglob("*.json") if p.stat().st_mtime >= start_ts - 1),
        key=lambda p: p.stat().st_mtime,
    )
    return str(candidates[-1]) if candidates else None


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    default_dataset_yaml = (
        repo_root
        / "experiments"
        / "external_benchmarks"
        / "memoryagentbench_local_smoke"
        / "infbench_sum_local_smoke.yaml"
    )
    default_local_data_dir = (
        repo_root
        / "experiments"
        / "external_benchmarks"
        / "memoryagentbench_local_smoke"
        / "infbench_sum_local_smoke"
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench-root", default="/tmp/MemoryAgentBench")
    parser.add_argument(
        "--python-bin",
        default="/usr/local/bin/python3",
        help="Python executable used to run MemoryAgentBench/main.py",
    )
    parser.add_argument(
        "--agent-config",
        default="/tmp/MemoryAgentBench/configs/agent_conf/Long_Context_Agents/Long_context_agent_gpt-4o-mini.yaml",
    )
    parser.add_argument(
        "--model",
        default="qwen/qwen3.5-397b-a17b",
        help="Model override injected into the agent config before launch.",
    )
    parser.add_argument("--dataset-config", default=str(default_dataset_yaml))
    parser.add_argument("--local-data-dir", default=str(default_local_data_dir))
    parser.add_argument("--sub-dataset", default="infbench_sum_local_smoke")
    parser.add_argument("--max-test-queries", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--enforce-mechanism-contract", action="store_true", default=True)
    parser.add_argument(
        "--openai-base-url",
        default="https://openrouter.ai/api/v1",
        help="Applied only when OPENAI_BASE_URL is unset.",
    )
    parser.add_argument(
        "--result-json",
        default=str(
            repo_root
            / "experiments"
            / "external_benchmarks"
            / "memoryagentbench_local_smoke"
            / "run_result.json"
        ),
    )
    args = parser.parse_args()

    bench_root = Path(args.bench_root).resolve()
    if not bench_root.exists():
        raise FileNotFoundError(f"MemoryAgentBench root not found: {bench_root}")

    # Ensure OpenRouter-backed OpenAI envs are present when only OPENROUTER_API_KEY is set.
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
    if not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = args.openai_base_url

    source_agent_config = Path(args.agent_config).resolve()
    with source_agent_config.open("r", encoding="utf-8") as f:
        agent_yaml = yaml.safe_load(f)
    model_override = (args.model or "").strip()
    runtime_model = normalize_model_name(model_override or str(agent_yaml.get("model", "")))
    agent_config = source_agent_config
    if model_override:
        agent_yaml["model"] = model_override
        resolved_cfg = Path(args.result_json).resolve().parent / "agent_config_resolved.yaml"
        resolved_cfg.parent.mkdir(parents=True, exist_ok=True)
        with resolved_cfg.open("w", encoding="utf-8") as f:
            yaml.safe_dump(agent_yaml, f, sort_keys=False)
        agent_config = resolved_cfg
    assert_expected_model(runtime_model)
    print(f"[MODEL_PIN] MODEL_EXPECTED={os.environ.get('MODEL_EXPECTED', '')} runtime={runtime_model}")

    dataset_config = Path(args.dataset_config).resolve()
    with dataset_config.open("r", encoding="utf-8") as f:
        dataset_yaml = yaml.safe_load(f)

    nltk_status = bootstrap_nltk()
    staged = stage_local_dataset(
        bench_root=bench_root,
        local_data_dir=Path(args.local_data_dir).resolve(),
        sub_dataset=args.sub_dataset,
        enforce_mechanism_contract=args.enforce_mechanism_contract,
    )

    cmd = [
        args.python_bin,
        "main.py",
        "--agent_config",
        str(agent_config),
        "--dataset_config",
        str(dataset_config),
        "--max_test_queries_ablation",
        str(args.max_test_queries),
    ]
    if args.force:
        cmd.append("--force")

    start_ts = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(bench_root),
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )

    latest_output = find_latest_output_json(bench_root, start_ts)
    run_id = f"memoryagentbench_local_{int(start_ts)}"

    result = {
        "metadata": make_metadata(
            repo_root=repo_root,
            model_name=runtime_model,
            seed=args.seed,
            run_id=run_id,
            extra={"benchmark": "memoryagentbench_local"},
        ),
        "command": cmd,
        "cwd": str(bench_root),
        "returncode": proc.returncode,
        "nltk_bootstrap": nltk_status,
        "enforce_mechanism_contract": args.enforce_mechanism_contract,
        "source_agent_config": str(source_agent_config),
        "resolved_agent_config": str(agent_config),
        "model_override": model_override or None,
        "staged_files": staged,
        "dataset_config": str(dataset_config),
        "dataset_name": dataset_yaml.get("dataset"),
        "sub_dataset": dataset_yaml.get("sub_dataset"),
        "latest_output_json": latest_output,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }

    result_path = Path(args.result_json).resolve()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({"result_json": str(result_path), "returncode": proc.returncode}, indent=2))
    if proc.returncode != 0:
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
