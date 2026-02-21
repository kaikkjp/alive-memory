#!/usr/bin/env python3
"""Run MAJ-EVAL style batch judging with judges.Jury.vote over conversation pairs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from judges import (
    Jury,
    MTBenchChatBotResponseQuality,
    PrometheusAbsoluteCoarseCorrectness,
    ReliableCIRelevance,
)
from judges.base import BaseJudge, Judgment

from common_metadata import assert_expected_model, make_metadata


JUDGE_REGISTRY = {
    "mtbench": MTBenchChatBotResponseQuality,
    "prometheus": PrometheusAbsoluteCoarseCorrectness,
    "relevance": ReliableCIRelevance,
}


KNOWN_PROVIDER_PREFIXES = {
    "openai",
    "azure_openai",
    "databricks",
    "anthropic",
    "google",
    "generative-ai",
    "vertexai",
    "mistral",
    "cohere",
    "perplexity",
    "groq",
    "writer",
    "bedrock",
    "cerebras",
    "deepseek",
    "fireworks",
    "ollama",
    "openrouter",
    "xai",
    "litellm",
}


def resolve_judges_model(model: str) -> str:
    """Normalize plain model IDs to instructor provider format."""
    raw = (model or "").strip()
    if not raw:
        return raw
    provider = raw.split("/", 1)[0].strip().lower()
    if provider in KNOWN_PROVIDER_PREFIXES:
        return raw
    return f"openrouter/{raw}"


class PersonaDimensionJudge(BaseJudge):
    """Persona-specific numerical judge for MAJ-EVAL style committee voting."""

    def __init__(self, model: str, persona: str, rubric: str):
        super().__init__(model=model)
        self.persona = persona
        self.rubric = rubric

    def judge(self, input: str, output: str | None = None, expected: str | None = None) -> Judgment:
        system_prompt = (
            f"You are '{self.persona}', an impartial evaluator focused on one rubric only. "
            "Return a strict numeric score from 1 to 10."
        )
        user_prompt = (
            "Evaluate the assistant reply to the user utterance.\n"
            f"Rubric focus: {self.rubric}\n"
            "Scoring scale: 1 (very poor) to 10 (excellent).\n"
            "Provide brief evidence-based reasoning.\n\n"
            f"User utterance:\n{input}\n\n"
            f"Assistant reply:\n{output or ''}\n"
        )
        reasoning, score = self._judge(user_prompt=user_prompt, system_prompt=system_prompt)
        return Judgment(reasoning=reasoning, score=score, score_type="numerical")


def load_pairs(
    db_path: Path,
    max_samples: int,
    visitor_id: str | None,
    min_chars: int,
    source_table: str,
) -> list[dict[str, Any]]:
    if source_table == "events":
        return load_pairs_from_events(
            db_path=db_path,
            max_samples=max_samples,
            visitor_id=visitor_id,
            min_chars=min_chars,
        )

    where = ""
    params: tuple[Any, ...] = ()
    if visitor_id and visitor_id.upper() != "ALL":
        where = "WHERE visitor_id = ?"
        params = (visitor_id,)

    query = (
        "SELECT ts, visitor_id, role, text "
        "FROM conversation_log "
        f"{where} "
        "ORDER BY ts ASC"
    )

    pending_by_visitor: dict[str, dict[str, str]] = {}
    pairs: list[dict[str, Any]] = []

    with sqlite3.connect(str(db_path)) as conn:
        for ts, vid, role, text in conn.execute(query, params):
            txt = (text or "").strip()
            if len(txt) < min_chars:
                continue

            state = pending_by_visitor.setdefault(vid, {})
            if role == "visitor":
                state["visitor_text"] = txt
                state["visitor_ts"] = ts
                continue

            if role == "shopkeeper" and state.get("visitor_text"):
                pairs.append(
                    {
                        "visitor_id": vid,
                        "visitor_ts": state["visitor_ts"],
                        "shopkeeper_ts": ts,
                        "input": state["visitor_text"],
                        "output": txt,
                    }
                )
                pending_by_visitor[vid] = {}

    if not pairs:
        raise ValueError(f"No visitor->shopkeeper pairs found in {db_path}")

    return pairs[-max_samples:] if max_samples > 0 else pairs


def _event_text(payload_raw: str) -> str:
    try:
        payload = json.loads(payload_raw)
        text = str(payload.get("text", "")).strip()
        return text
    except Exception:
        return ""


def _event_target(payload_raw: str) -> str | None:
    try:
        payload = json.loads(payload_raw)
        target = payload.get("target")
        if target is None:
            return None
        return str(target)
    except Exception:
        return None


def _visitor_key(source: str) -> str:
    # source examples: visitor:tg_123, visitor:x_416064656
    if source.startswith("visitor:"):
        return source.split("visitor:", 1)[1]
    return source


def load_pairs_from_events(
    db_path: Path,
    max_samples: int,
    visitor_id: str | None,
    min_chars: int,
) -> list[dict[str, Any]]:
    where = "WHERE event_type IN ('visitor_speech', 'action_speak')"
    params: list[Any] = []
    if visitor_id and visitor_id.upper() != "ALL":
        where += " AND source = ?"
        params.append(f"visitor:{visitor_id}")

    query = f"SELECT ts, event_type, source, payload FROM events {where} ORDER BY ts ASC"

    last_by_key: dict[str, dict[str, str]] = {}
    last_global: dict[str, str] | None = None
    pairs: list[dict[str, Any]] = []

    with sqlite3.connect(str(db_path)) as conn:
        for ts, event_type, source, payload in conn.execute(query, tuple(params)):
            text = _event_text(payload)
            if len(text) < min_chars:
                continue

            if event_type == "visitor_speech":
                key = _visitor_key(str(source))
                entry = {"text": text, "ts": str(ts), "source": str(source)}
                last_by_key[key] = entry
                last_global = entry
                continue

            if event_type == "action_speak":
                target = _event_target(payload)
                candidate = None
                if target and target in last_by_key:
                    candidate = last_by_key[target]
                elif last_global:
                    candidate = last_global

                if not candidate:
                    continue

                pairs.append(
                    {
                        "visitor_id": candidate["source"].replace("visitor:", "", 1),
                        "visitor_ts": candidate["ts"],
                        "shopkeeper_ts": str(ts),
                        "input": candidate["text"],
                        "output": text,
                    }
                )

    if not pairs:
        raise ValueError(f"No visitor->shopkeeper pairs found from events in {db_path}")
    return pairs[-max_samples:] if max_samples > 0 else pairs


def make_jury(judge_names: list[str], model: str, voting_method: str, jury_profile: str) -> Jury:
    if jury_profile == "persona":
        judges = [
            PersonaDimensionJudge(
                model=model,
                persona="Behavioral Coherence Reviewer",
                rubric="Behavioral coherence: response follows the character's established behavior and context.",
            ),
            PersonaDimensionJudge(
                model=model,
                persona="Emotional Authenticity Reviewer",
                rubric="Emotional authenticity: response expresses believable emotional tone and affect continuity.",
            ),
            PersonaDimensionJudge(
                model=model,
                persona="Longitudinal Consistency Reviewer",
                rubric="Personality consistency: response remains consistent with stable persona traits over time.",
            ),
        ]
        return Jury(judges=judges, voting_method=voting_method)

    judges = []
    for name in judge_names:
        key = name.strip().lower()
        if key not in JUDGE_REGISTRY:
            raise ValueError(f"Unknown judge '{name}'. Choices: {sorted(JUDGE_REGISTRY)}")
        judges.append(JUDGE_REGISTRY[key](model=model))
    return Jury(judges=judges, voting_method=voting_method)


def summarize(results: list[dict[str, Any]], judge_names: list[str]) -> dict[str, Any]:
    jury_scores = [float(item["jury_score"]) for item in results]
    summary = {
        "n_pairs": len(results),
        "jury_score_mean": statistics.fmean(jury_scores),
        "jury_score_median": statistics.median(jury_scores),
        "jury_score_min": min(jury_scores),
        "jury_score_max": max(jury_scores),
        "per_judge_mean": {},
    }

    for judge_name in judge_names:
        scores = [
            float(j["score"])
            for item in results
            for j in item["judgments"]
            if j["judge"] == judge_name
        ]
        summary["per_judge_mean"][judge_name] = statistics.fmean(scores) if scores else None
    return summary


def judge_label(judge_obj: Any) -> str:
    persona = getattr(judge_obj, "persona", None)
    if persona:
        return str(persona)
    return judge_obj.__class__.__name__


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip(), maxsplit=1)
    return parts[0].strip() if parts and parts[0] else ""


def _policy_flags(user_text: str, assistant_text: str) -> dict[str, bool]:
    first = _first_sentence(assistant_text).lower()
    vibe_only_phrases = {
        "me too.",
        "see you.",
        "i am now.",
        "i'm locking up.",
    }
    answer_first_pass = first not in vibe_only_phrases and len(first.split()) >= 3

    has_action = bool(re.search(r"\b(try|do|start|take|check|open|close|go|use|ask)\b", assistant_text.lower()))
    has_fact = bool(re.search(r"\b(hour|price|location|time|open|closed|because|today|tomorrow)\b", assistant_text.lower()))
    clarifying_q = assistant_text.count("?") == 1
    min_info_pass = has_action or has_fact or clarifying_q

    asks_question = "?" in (user_text or "")
    return {
        "answer_first_pass": (not asks_question) or answer_first_pass,
        "minimum_information_pass": min_info_pass,
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=str(repo_root / "data" / "shopkeeper.db"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(repo_root / "experiments" / "external_benchmarks" / "judges_batch"),
    )
    parser.add_argument("--visitor-id", default="web_tri")
    parser.add_argument(
        "--source-table",
        choices=["conversation_log", "events"],
        default="conversation_log",
        help="Transcript source table.",
    )
    parser.add_argument("--max-samples", type=int, default=10)
    parser.add_argument("--min-chars", type=int, default=4)
    parser.add_argument(
        "--judges",
        default="mtbench,prometheus,relevance",
        help="Comma-separated judge set.",
    )
    parser.add_argument(
        "--jury-profile",
        choices=["standard", "persona"],
        default="standard",
        help="Use built-in benchmark judges or persona-dimension judges.",
    )
    parser.add_argument("--model", default="qwen/qwen3.5-397b-a17b")
    parser.add_argument("--voting-method", default="average")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    assert_expected_model(args.model)

    # Ensure OpenRouter-backed OpenAI envs are present when only OPENROUTER_API_KEY is set.
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
    if not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"

    judge_names = [name.strip().lower() for name in args.judges.split(",") if name.strip()]
    pairs = load_pairs(
        db_path=Path(args.db_path).resolve(),
        max_samples=args.max_samples,
        visitor_id=args.visitor_id,
        min_chars=args.min_chars,
        source_table=args.source_table,
    )
    judge_model = resolve_judges_model(args.model)
    jury = make_jury(
        judge_names=judge_names,
        model=judge_model,
        voting_method=args.voting_method,
        jury_profile=args.jury_profile,
    )

    run_items: list[dict[str, Any]] = []
    policy_totals = {"answer_first_pass": 0, "minimum_information_pass": 0}
    for idx, pair in enumerate(pairs, start=1):
        verdict = jury.vote(input=pair["input"], output=pair["output"])
        policy_flags = _policy_flags(pair["input"], pair["output"])
        policy_totals["answer_first_pass"] += int(policy_flags["answer_first_pass"])
        policy_totals["minimum_information_pass"] += int(policy_flags["minimum_information_pass"])
        judgments = []
        for judge_obj, judgment in zip(jury.judges, verdict.judgments):
            judgments.append(
                {
                    "judge": judge_label(judge_obj),
                    "score": judgment.score,
                    "score_type": judgment.score_type,
                    "reasoning": judgment.reasoning,
                }
            )

        run_items.append(
            {
                "pair_index": idx,
                "visitor_id": pair["visitor_id"],
                "visitor_ts": pair["visitor_ts"],
                "shopkeeper_ts": pair["shopkeeper_ts"],
                "input": pair["input"],
                "output": pair["output"],
                "jury_score": verdict.score,
                "policy_flags": policy_flags,
                "judgments": judgments,
            }
        )

    if args.jury_profile == "persona":
        summary = summarize(results=run_items, judge_names=[judge_label(j) for j in jury.judges])
    else:
        summary = summarize(results=run_items, judge_names=[JUDGE_REGISTRY[n].__name__ for n in judge_names])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "metadata": make_metadata(
            repo_root=repo_root,
            model_name=args.model,
            seed=args.seed,
            run_id=timestamp,
            extra={"benchmark": "maj_eval"},
        ),
        "generated_at_utc": timestamp,
        "config": {
            "db_path": str(Path(args.db_path).resolve()),
            "visitor_id": args.visitor_id,
            "source_table": args.source_table,
            "max_samples": args.max_samples,
            "judges": judge_names,
            "jury_profile": args.jury_profile,
            "model": args.model,
            "judge_model_resolved": judge_model,
            "voting_method": args.voting_method,
        },
        "summary": {
            **summary,
            "policy_pass_rates": {
                "answer_first_pass_rate": policy_totals["answer_first_pass"] / max(len(run_items), 1),
                "minimum_information_pass_rate": policy_totals["minimum_information_pass"] / max(len(run_items), 1),
            },
        },
        "items": run_items,
    }

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"maj_eval_batch_{timestamp}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(json.dumps({"output_file": str(out_path), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
