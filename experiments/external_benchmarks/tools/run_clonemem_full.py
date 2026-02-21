#!/usr/bin/env python3
"""Run full CloneMem flat retrieval sweep and patched auto-metric evaluation."""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common_metadata import make_metadata


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def patch_schema(node: Any) -> None:
    if isinstance(node, dict):
        if "digital_trace_ids" in node:
            mapped = as_list(node["digital_trace_ids"])
            node.setdefault("media_ids", mapped)
            node.setdefault("related_media_id", mapped)
        for v in node.values():
            patch_schema(v)
    elif isinstance(node, list):
        for item in node:
            patch_schema(item)


def run_cmd(cmd: list[str], cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    start = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env)
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "elapsed_seconds": time.time() - start,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-3000:],
    }


def metric_value(metric_json: Path, key: str, sub: str) -> float | None:
    try:
        with metric_json.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return float(payload.get(key, {}).get(sub))
    except Exception:
        return None


def load_retrieval_candidates(retrieval_file: Path) -> dict[str, list[str]]:
    with retrieval_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if "results" in payload and isinstance(payload["results"], dict):
        payload = payload["results"]

    out: dict[str, list[str]] = {}
    for qid, obj in payload.items():
        ranked = obj.get("ranked_items", []) if isinstance(obj, dict) else []
        seen = set()
        unique_chunk_ids: list[str] = []
        for item in ranked:
            if item.get("res_type") != "chunk":
                continue
            cid = item.get("chunk_id")
            if cid is None or cid in seen:
                continue
            seen.add(cid)
            unique_chunk_ids.append(str(cid))
        out[str(qid)] = unique_chunk_ids
    return out


def retrieval_k_sanity(
    retrieval_file: Path,
    seed: int,
    sample_size: int = 20,
) -> dict[str, Any]:
    cands = load_retrieval_candidates(retrieval_file)
    lengths = {qid: len(ids) for qid, ids in cands.items()}
    qids = list(cands.keys())
    rng = random.Random(seed)
    sampled = rng.sample(qids, k=min(sample_size, len(qids))) if qids else []
    sampled_lengths = [{"query_id": qid, "retrieved_candidates": lengths[qid]} for qid in sampled]

    ge20_qids = [qid for qid, n in lengths.items() if n >= 20]
    top_slice_assertions = []
    for qid in ge20_qids[:sample_size]:
        ids = cands[qid]
        top10 = ids[:10]
        top20 = ids[:20]
        if top10 == top20:
            raise AssertionError(f"k-slicing failure on query {qid}: top10 == top20 with len={len(ids)}")
        top_slice_assertions.append({"query_id": qid, "top10_ne_top20": True})

    return {
        "n_queries": len(qids),
        "n_queries_ge_20": len(ge20_qids),
        "sampled_candidate_lengths": sampled_lengths,
        "top_slice_assertions": top_slice_assertions,
        "max_candidates": max(lengths.values()) if lengths else 0,
        "min_candidates": min(lengths.values()) if lengths else 0,
    }


def monotonicity_sanity(metric_file: Path) -> dict[str, Any]:
    with metric_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    k10 = payload.get("k10", {})
    k20 = payload.get("k20", {})
    checks = {}
    for metric_name, v10 in k10.items():
        v20 = k20.get(metric_name)
        if isinstance(v10, (int, float)) and isinstance(v20, (int, float)):
            if float(v20) + 1e-12 < float(v10):
                raise AssertionError(
                    f"Monotonicity violated for {metric_name}: k20={v20} < k10={v10}"
                )
            checks[metric_name] = {"k10": v10, "k20": v20, "monotonic": True}
    return checks


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clone-root", default="/tmp/CloneMemBench")
    parser.add_argument("--python-bin", default="/usr/local/bin/python3")
    parser.add_argument(
        "--output-dir",
        default=str(repo_root / "experiments" / "external_benchmarks" / "clonemem_full_flat"),
    )
    parser.add_argument("--retrieve-k", type=int, default=50)
    parser.add_argument("--embedding-model", default="all-MiniLM-L6-v2")
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--outfile-prefix", default="overnight")
    parser.add_argument("--max-users", type=int, default=0, help="0 means all users.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--strict-k-sanity", action="store_true", default=True)
    args = parser.parse_args()

    clone_root = Path(args.clone_root).resolve()
    if not clone_root.exists():
        raise FileNotFoundError(f"CloneMemBench root not found: {clone_root}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.output_dir).resolve() / run_id
    retrieval_dir = run_dir / "retrieval"
    metrics_dir = run_dir / "metrics"
    qa_dir = run_dir / "patched_qa"
    for d in [run_dir, retrieval_dir, metrics_dir, qa_dir]:
        d.mkdir(parents=True, exist_ok=True)

    qa_files = sorted((clone_root / "data" / "releases").glob("*/*_benchmark_en.json"))
    if not qa_files:
        raise FileNotFoundError(f"No *_benchmark_en.json under {clone_root / 'data/releases'}")
    if args.max_users > 0:
        qa_files = qa_files[: args.max_users]

    env = os.environ.copy()
    if not env.get("OPENAI_API_KEY") and env.get("OPENROUTER_API_KEY"):
        env["OPENAI_API_KEY"] = env["OPENROUTER_API_KEY"]
    if not env.get("OPENAI_BASE_URL"):
        env["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"

    run_items: list[dict[str, Any]] = []
    any_ge_20 = False
    k_sanity_failures = 0
    monotonic_failures = 0
    for qa_file in qa_files:
        with qa_file.open("r", encoding="utf-8") as f:
            qa_payload = json.load(f)
        patch_schema(qa_payload)
        qa_wrapper = qa_payload if isinstance(qa_payload, list) else [qa_payload]
        user_id = qa_wrapper[0]["person_id"]

        patched_qa = qa_dir / f"{qa_file.stem}_patched_wrapper.json"
        with patched_qa.open("w", encoding="utf-8") as f:
            json.dump(qa_wrapper, f, indent=2, ensure_ascii=False)

        eval_cmd = [
            args.python_bin,
            "eval_flat.py",
            "--in_file",
            str(qa_file),
            "--output_dir",
            str(retrieval_dir),
            "--outfile_prefix",
            args.outfile_prefix,
            "--embedding_model",
            args.embedding_model,
            "--join_method",
            "none",
            "--use_chunk",
            "--retrieve_k",
            str(args.retrieve_k),
            "--num_workers",
            str(args.num_workers),
        ]
        eval_res = run_cmd(eval_cmd, cwd=clone_root / "src" / "clonemem-eval", env=env)

        retrieval_file = (
            retrieval_dir
            / f"{args.outfile_prefix}_{user_id}_{args.embedding_model}-no_expansion-none-use_chunk.json"
        )
        metric_file = metrics_dir / f"metrics_{user_id}.json"

        metric_res: dict[str, Any] = {"skipped": True}
        k_sanity: dict[str, Any] | None = None
        monotonic: dict[str, Any] | None = None
        if retrieval_file.exists():
            try:
                k_sanity = retrieval_k_sanity(retrieval_file, seed=args.seed, sample_size=20)
                if k_sanity.get("n_queries_ge_20", 0) > 0:
                    any_ge_20 = True
            except Exception as exc:
                k_sanity_failures += 1
                k_sanity = {"error": str(exc)}
            metric_in_file = retrieval_dir / f"metricin_{user_id}.json"
            shutil.copy2(retrieval_file, metric_in_file)
            metric_cmd = [
                args.python_bin,
                str(clone_root / "src" / "clonemem-eval" / "eval" / "compute_auto_metrics_for_clonemem.py"),
                "--in_file",
                str(metric_in_file),
                "--qa_file",
                str(patched_qa),
                "--out_file",
                str(metric_file),
            ]
            metric_res = run_cmd(metric_cmd, cwd=repo_root, env=env)
            if metric_file.exists():
                try:
                    monotonic = monotonicity_sanity(metric_file)
                except Exception as exc:
                    monotonic_failures += 1
                    monotonic = {"error": str(exc)}

        run_items.append(
            {
                "qa_file": str(qa_file),
                "user_id": user_id,
                "patched_qa": str(patched_qa),
                "retrieval_file": str(retrieval_file),
                "metric_file": str(metric_file) if metric_file.exists() else None,
                "eval": eval_res,
                "metric": metric_res,
                "retrieval_k_sanity": k_sanity,
                "metric_monotonicity_sanity": monotonic,
                "k10_recall_flat": metric_value(metric_file, "k10", "recall_flat") if metric_file.exists() else None,
                "k10_recall_any_any": metric_value(metric_file, "k10", "recall_any_any") if metric_file.exists() else None,
            }
        )

    recall_flat = [x["k10_recall_flat"] for x in run_items if x["k10_recall_flat"] is not None]
    recall_any_any = [x["k10_recall_any_any"] for x in run_items if x["k10_recall_any_any"] is not None]
    summary = {
        "total_users": len(run_items),
        "metrics_users": len(recall_flat),
        "k10_recall_flat_mean": statistics.fmean(recall_flat) if recall_flat else None,
        "k10_recall_any_any_mean": statistics.fmean(recall_any_any) if recall_any_any else None,
        "k_sanity_any_query_ge20": any_ge_20,
        "k_sanity_failures": k_sanity_failures,
        "metric_monotonic_failures": monotonic_failures,
        "failed_eval_users": sum(1 for x in run_items if x["eval"]["returncode"] != 0),
        "failed_metric_users": sum(
            1 for x in run_items if x["retrieval_file"] and x["metric"].get("returncode", 0) != 0
        ),
    }

    payload = {
        "metadata": make_metadata(
            repo_root=repo_root,
            model_name=f"openai/{args.embedding_model}",
            seed=args.seed,
            run_id=run_id,
            extra={"benchmark": "clonemem_flat"},
        ),
        "run_id": run_id,
        "clone_root": str(clone_root),
        "output_dir": str(run_dir),
        "summary": summary,
        "items": run_items,
    }
    summary_path = run_dir / "run_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(json.dumps({"run_summary": str(summary_path), "summary": summary}, indent=2))
    if args.strict_k_sanity:
        if not any_ge_20:
            raise SystemExit("Blocking: no query had >=20 retrieved candidates; k20 cannot be validated.")
        if k_sanity_failures > 0 or monotonic_failures > 0:
            raise SystemExit("Blocking: k-sanity or monotonicity checks failed.")


if __name__ == "__main__":
    main()
