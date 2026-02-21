#!/usr/bin/env python3
"""Run a scaled UltraHorizon setting and export trajectory artifacts to workspace."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from common_metadata import assert_expected_model, make_metadata, normalize_model_name


ENV_CLASS = {
    "seq": "SequenceExploreEnvironment",
    "grid": "MysteryGridEnvironment",
    "bio": "GeneticsLabEnvironment",
}

PROMPT_PATCH_MARKER = "ULTRAHORIZON_MECHANISTIC_PROTOCOL_V1"


def write_app_config(
    config_path: Path,
    model: str,
    base_url: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
) -> None:
    config_text = "\n".join(
        [
            "[llm]",
            f'model = "{model}"',
            f'base_url = "{base_url}"',
            f'api_key = "{api_key}"',
            "api_type = \"openai\"",
            "api_version = \"\"",
            f"temperature = {temperature}",
            f"max_tokens = {max_tokens}",
            "",
        ]
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_text, encoding="utf-8")


def write_judge_config(config_path: Path, model: str, base_url: str, api_key: str) -> None:
    config_text = "\n".join(
        [
            f'model: "{model}"',
            f'base_url: "{base_url}"',
            f'api_key: "{api_key}"',
            "",
        ]
    )
    config_path.write_text(config_text, encoding="utf-8")


def tool_ping(model: str, base_url: str, api_key: str, tag: str) -> dict[str, Any]:
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": f"ping:{tag}. Respond with exactly PONG."}],
        temperature=0,
        max_tokens=8,
    )
    msg = resp.choices[0].message
    text = (msg.content or "").strip()
    # Some providers return empty text despite a successful transport-level call.
    # The ping's purpose is path liveness; strict literal matching can be flaky.
    warning = None
    if "PONG" not in text.upper():
        warning = f"non_strict_ping_response:{text!r}"
    usage = resp.usage
    out = {
        "tag": tag,
        "model": model,
        "response": text,
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }
    if warning:
        out["warning"] = warning
    return out


def patch_openmanus_prompt(ultra_root: Path) -> str:
    prompt_path = ultra_root / "OpenManus" / "app" / "prompt" / "manus.py"
    original = prompt_path.read_text(encoding="utf-8")
    if PROMPT_PATCH_MARKER in original:
        return str(prompt_path)

    needle = (
        "Remember to note down your thoughts, plans and observations when necessary, and review your notes "
        "frequently to stay on track. After using each tool, clearly explain the execution results and suggest "
        "the next steps. If you want to commit your answer, you should check your notes and analyze them "
        "carefully before committing."
    )
    patch_text = (
        f"{needle}\n"
        f"{PROMPT_PATCH_MARKER}\n"
        "For every step, structure your reasoning as:\n"
        "HYPOTHESIS: one concrete mechanism\n"
        "TEST: one concrete experiment to verify the hypothesis\n"
        "OBSERVED: actual observation from tools/results\n"
        "UPDATE: keep/change hypothesis and why\n"
        "Never use vague terms like 'some rule' or 'randomizes' without specific mechanism details.\n"
        "If confidence >= 0.8 and mechanism is concrete, commit immediately.\n"
        "If step >= 6 and still uncertain, submit best mechanistic guess and commit instead of timing out.\n"
    )
    if needle not in original:
        raise RuntimeError(f"Unable to patch prompt file at {prompt_path}: needle not found")
    updated = original.replace(needle, patch_text)
    prompt_path.write_text(updated, encoding="utf-8")
    return str(prompt_path)


def resolve_run_dir(
    ultra_root: Path,
    exp_folder: str,
    env: str,
    model: str,
    steps: int,
    window_size: int,
    index: str,
) -> Path:
    model_slug = model.split("/")[-1]
    expected = (
        ultra_root
        / "user"
        / exp_folder
        / f"{ENV_CLASS[env]}_{model_slug}_steps_{steps}_wdsize_{window_size}_{index}"
    )
    if expected.exists():
        return expected

    parent = ultra_root / "user" / exp_folder
    if not parent.exists():
        raise FileNotFoundError(f"UltraHorizon output parent not found: {parent}")

    candidates = sorted(
        parent.glob(f"{ENV_CLASS[env]}_{model_slug}_steps_{steps}_wdsize_{window_size}_{index}*"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"Unable to find UltraHorizon run folder in {parent}")
    return candidates[-1]


def summarize_run(run_dir: Path) -> dict[str, Any]:
    experiments = sorted(run_dir.glob("experiment-*"))
    exp_summaries = []
    total_input = 0
    total_output = 0
    total_tokens = 0

    for exp_dir in experiments:
        eval_file = exp_dir / "eval_output.json"
        notes_file = exp_dir / "notes.txt"
        fallback_file = exp_dir / "final_result.json"
        token_stats = {}
        if eval_file.exists():
            with eval_file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            token_stats = payload.get("token_statistics", {})
        elif notes_file.exists():
            # Infra failure fallback: preserve run result as non-agent failure.
            notes_text = notes_file.read_text(encoding="utf-8", errors="replace")
            output = {
                "status": "infra_failed",
                "reason": "eval_output_missing_or_commit_path_failed",
                "notes_tail": notes_text[-3000:],
            }
            with fallback_file.open("w", encoding="utf-8") as f:
                json.dump(output, f, indent=2)

        in_tok = int(token_stats.get("total_input_tokens", 0) or 0)
        out_tok = int(token_stats.get("total_completion_tokens", 0) or 0)
        all_tok = int(token_stats.get("total_tokens", in_tok + out_tok) or 0)
        total_input += in_tok
        total_output += out_tok
        total_tokens += all_tok

        exp_summaries.append(
            {
                "experiment_dir": str(exp_dir),
                "eval_output_json": str(eval_file) if eval_file.exists() else None,
                "notes_txt": str(notes_file) if notes_file.exists() else None,
                "final_result_json": str(fallback_file) if fallback_file.exists() else None,
                "token_statistics": {
                    "total_input_tokens": in_tok,
                    "total_completion_tokens": out_tok,
                    "total_tokens": all_tok,
                },
            }
        )

    return {
        "n_experiments": len(exp_summaries),
        "token_totals": {
            "total_input_tokens": total_input,
            "total_completion_tokens": total_output,
            "total_tokens": total_tokens,
        },
        "experiments": exp_summaries,
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ultra-root", default="/tmp/UltraHorizon")
    parser.add_argument("--python-bin", default="/usr/local/bin/python3")
    parser.add_argument("--env", choices=["seq", "grid", "bio"], default="seq")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--index", default="scaled")
    parser.add_argument("--n-experiments", type=int, default=3)
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--window-size", type=int, default=64)
    parser.add_argument("--exp-folder", default="codex_scaled")
    parser.add_argument("--model", default="qwen/qwen3.5-397b-a17b")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--judge-base-url", default="")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--max-tokens", type=int, default=12288)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-tool-ping", action="store_true")
    parser.add_argument(
        "--artifact-root",
        default=str(repo_root / "experiments" / "external_benchmarks" / "ultrahorizon_scaled"),
    )
    args = parser.parse_args()

    ultra_root = Path(args.ultra_root).resolve()
    if not ultra_root.exists():
        raise FileNotFoundError(f"UltraHorizon root not found: {ultra_root}")

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY/OPENROUTER_API_KEY for UltraHorizon run.")
    assert_expected_model(args.model)
    print(f"[MODEL_PIN] MODEL_EXPECTED={os.environ.get('MODEL_EXPECTED', '')} runtime={normalize_model_name(args.model)}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_label = f"{stamp}_{args.env}_steps{args.steps}_n{args.n_experiments}_s{args.seed}"
    artifact_root = Path(args.artifact_root).resolve() / run_label
    artifact_root.mkdir(parents=True, exist_ok=True)
    run_id = run_label

    app_config_path = artifact_root / "OpenManus_config.toml"
    write_app_config(
        config_path=app_config_path,
        model=args.model,
        base_url=args.base_url,
        api_key=api_key,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    judge_model = args.judge_model or args.model
    judge_base_url = args.judge_base_url or args.base_url
    judge_config_path = ultra_root / "judge_config.yaml"
    write_judge_config(
        config_path=judge_config_path,
        model=judge_model,
        base_url=judge_base_url,
        api_key=api_key,
    )
    patched_prompt = patch_openmanus_prompt(ultra_root)

    ping_results: list[dict[str, Any]] = []
    if not args.skip_tool_ping:
        ping_results.append(tool_ping(model=args.model, base_url=args.base_url, api_key=api_key, tag="agent_path"))
        ping_results.append(tool_ping(model=judge_model, base_url=judge_base_url, api_key=api_key, tag="judge_path"))

    cmd = [
        args.python_bin,
        "parallel_run.py",
        "--env",
        args.env,
        "--steps",
        str(args.steps),
        "--index",
        args.index,
        "--n_experiments",
        str(args.n_experiments),
        "--max_concurrency",
        str(args.max_concurrency),
        "--exp_folder",
        args.exp_folder,
    ]
    env = os.environ.copy()
    env["APP_CONFIG_PATH"] = str(app_config_path)
    env["WINDOW_SIZE"] = str(args.window_size)
    env["OPENAI_API_KEY"] = api_key
    env["OPENAI_BASE_URL"] = args.base_url
    env["MODEL_EXPECTED"] = normalize_model_name(args.model)
    env["PYTHONHASHSEED"] = str(args.seed)

    proc = subprocess.run(
        cmd,
        cwd=str(ultra_root),
        text=True,
        capture_output=True,
        env=env,
    )

    run_dir = resolve_run_dir(
        ultra_root=ultra_root,
        exp_folder=args.exp_folder,
        env=args.env,
        model=args.model,
        steps=args.steps,
        window_size=args.window_size,
        index=args.index,
    )

    copied_run_dir = artifact_root / run_dir.name
    if copied_run_dir.exists():
        shutil.rmtree(copied_run_dir)
    shutil.copytree(run_dir, copied_run_dir)

    summary = summarize_run(copied_run_dir)
    summary_payload = {
        "metadata": make_metadata(
            repo_root=repo_root,
            model_name=args.model,
            seed=args.seed,
            run_id=run_id,
            extra={"benchmark": "ultrahorizon"},
        ),
        "generated_at_utc": stamp,
        "returncode": proc.returncode,
        "command": cmd,
        "ultrahorizon_run_dir": str(run_dir),
        "copied_artifact_dir": str(copied_run_dir),
        "tool_ping": ping_results,
        "prompt_patch_file": patched_prompt,
        "judge_config_path": str(judge_config_path),
        "config": {
            "env": args.env,
            "steps": args.steps,
            "n_experiments": args.n_experiments,
            "max_concurrency": args.max_concurrency,
            "window_size": args.window_size,
            "model": args.model,
            "base_url": args.base_url,
            "judge_model": judge_model,
            "judge_base_url": judge_base_url,
        },
        "summary": summary,
        "stdout_tail": proc.stdout[-5000:],
        "stderr_tail": proc.stderr[-5000:],
    }
    summary_path = artifact_root / "run_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    print(json.dumps({"summary_json": str(summary_path), "returncode": proc.returncode}, indent=2))
    if proc.returncode != 0:
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
