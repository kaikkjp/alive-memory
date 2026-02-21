#!/usr/bin/env python3
"""Launch full MemoryAgentBench evaluations across config set with SSL/NLTK bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import nltk
import yaml

from common_metadata import assert_expected_model, make_metadata, normalize_model_name


try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context


DEFAULT_CONFIGS = [
    "configs/data_conf/Accurate_Retrieval/EventQA/Eventqa_full.yaml",
    "configs/data_conf/Accurate_Retrieval/LongMemEval/Longmemeval_s.yaml",
    "configs/data_conf/Accurate_Retrieval/LongMemEval/Longmemeval_s_star.yaml",
    "configs/data_conf/Conflict_Resolution/Factconsolidation_mh_262k.yaml",
    "configs/data_conf/Conflict_Resolution/Factconsolidation_sh_262k.yaml",
    "configs/data_conf/Long_Range_Understanding/Detective_QA.yaml",
    "configs/data_conf/Long_Range_Understanding/InfBench_sum.yaml",
    "configs/data_conf/Test_Time_Learning/ICL/ICL_banking77.yaml",
    "configs/data_conf/Test_Time_Learning/ICL/ICL_clinic150.yaml",
    "configs/data_conf/Test_Time_Learning/ICL/ICL_nlu.yaml",
    "configs/data_conf/Test_Time_Learning/ICL/ICL_trec_coarse.yaml",
    "configs/data_conf/Test_Time_Learning/ICL/ICL_trec_fine.yaml",
    "configs/data_conf/Test_Time_Learning/Recsys/Recsys_redial_full.yaml",
]


def bootstrap_nltk() -> dict[str, bool]:
    return {
        "punkt": bool(nltk.download("punkt", quiet=True)),
        "punkt_tab": bool(nltk.download("punkt_tab", quiet=True)),
    }


def newest_json(root: Path, after: float) -> str | None:
    if not root.exists():
        return None
    files = sorted(
        (p for p in root.rglob("*.json") if p.stat().st_mtime >= after - 1),
        key=lambda p: p.stat().st_mtime,
    )
    return str(files[-1]) if files else None


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench-root", default="/tmp/MemoryAgentBench")
    parser.add_argument("--python-bin", default="/usr/local/bin/python3")
    parser.add_argument(
        "--agent-config",
        default="/tmp/MemoryAgentBench/configs/agent_conf/Long_Context_Agents/Long_context_agent_gpt-4o-mini.yaml",
    )
    parser.add_argument(
        "--model",
        default="qwen/qwen3.5-397b-a17b",
        help="Model override injected into the agent config before launch.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(repo_root / "experiments" / "external_benchmarks" / "memoryagentbench_full"),
    )
    parser.add_argument(
        "--config-list",
        default=",".join(DEFAULT_CONFIGS),
        help="Comma-separated dataset config paths relative to bench root.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    args = parser.parse_args()

    bench_root = Path(args.bench_root).resolve()
    if not bench_root.exists():
        raise FileNotFoundError(f"MemoryAgentBench root not found: {bench_root}")

    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
    if not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.output_dir).resolve() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    source_agent_config_path = Path(args.agent_config).resolve()
    with source_agent_config_path.open("r", encoding="utf-8") as f:
        agent_yaml = yaml.safe_load(f)
    model_override = (args.model or "").strip()
    runtime_model = normalize_model_name(model_override or str(agent_yaml.get("model", "")))
    agent_config_path = source_agent_config_path
    if model_override:
        agent_yaml["model"] = model_override
        resolved_cfg = out_dir / "agent_config_resolved.yaml"
        with resolved_cfg.open("w", encoding="utf-8") as f:
            yaml.safe_dump(agent_yaml, f, sort_keys=False)
        agent_config_path = resolved_cfg
    assert_expected_model(runtime_model)
    print(f"[MODEL_PIN] MODEL_EXPECTED={os.environ.get('MODEL_EXPECTED', '')} runtime={runtime_model}")

    status = {
        "metadata": make_metadata(
            repo_root=repo_root,
            model_name=runtime_model,
            seed=args.seed,
            run_id=run_id,
            extra={"benchmark": "memoryagentbench_full"},
        ),
        "run_id": run_id,
        "bench_root": str(bench_root),
        "agent_config": str(agent_config_path),
        "source_agent_config": str(source_agent_config_path),
        "model_override": model_override or None,
        "nltk_bootstrap": bootstrap_nltk(),
        "results": [],
    }

    configs = [c.strip() for c in args.config_list.split(",") if c.strip()]
    outputs_root = bench_root / "outputs"
    for rel_cfg in configs:
        cfg = (bench_root / rel_cfg).resolve()
        start = time.time()
        cmd = [
            args.python_bin,
            "main.py",
            "--agent_config",
            str(agent_config_path),
            "--dataset_config",
            str(cfg),
        ]
        if args.force:
            cmd.append("--force")

        proc = subprocess.run(
            cmd,
            cwd=str(bench_root),
            text=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        elapsed = time.time() - start
        item = {
            "dataset_config": str(cfg),
            "returncode": proc.returncode,
            "elapsed_seconds": elapsed,
            "latest_output_json": newest_json(outputs_root, start),
            "stdout_tail": proc.stdout[-3000:],
            "stderr_tail": proc.stderr[-3000:],
        }
        status["results"].append(item)

        per_cfg_name = cfg.stem + ".json"
        with (out_dir / per_cfg_name).open("w", encoding="utf-8") as f:
            json.dump(item, f, indent=2)

        if proc.returncode != 0 and not args.continue_on_error:
            break

    summary = {
        "total": len(status["results"]),
        "succeeded": sum(1 for r in status["results"] if r["returncode"] == 0),
        "failed": sum(1 for r in status["results"] if r["returncode"] != 0),
    }
    status["summary"] = summary

    status_path = out_dir / "run_summary.json"
    with status_path.open("w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

    print(json.dumps({"run_summary": str(status_path), "summary": summary}, indent=2))
    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
