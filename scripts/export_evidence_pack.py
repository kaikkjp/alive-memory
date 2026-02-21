#!/usr/bin/env python3
"""Export a 7-day evidence pack from a production SQLite snapshot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
JSON_HEADER: dict[str, Any] | None = None


def parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    for fmt in (
        None,
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            continue
    return None


def iso_utc(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def in_window(dt: datetime | None, start: datetime, end: datetime) -> bool:
    return dt is not None and start <= dt <= end


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def sha12(value: str | None) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def tokenize_words(text: str | None) -> set[str]:
    if not text:
        return set()
    words = re.split(r"[^a-zA-Z0-9_]+", text.lower())
    return {w for w in words if len(w) >= 4}


def resolve_cycle_id_for_ts(
    ts: datetime | None,
    cycle_pairs: list[tuple[datetime, str]],
    future_slack_seconds: int = 20 * 60,
    past_slack_seconds: int = 5 * 60,
) -> tuple[str, str, int]:
    """Resolve a cycle_id from cycle end timestamps.

    Returns: (cycle_id, method, delta_seconds)
    """
    if ts is None or not cycle_pairs:
        return ("", "unresolved", -1)

    # Prefer the first cycle end timestamp at/after LLM call time.
    for end_ts, cid in cycle_pairs:
        delta = int((end_ts - ts).total_seconds())
        if 0 <= delta <= future_slack_seconds:
            return (cid, "next_cycle_end", delta)

    # Fallback to nearest prior cycle end if very close.
    prior = [(end_ts, cid) for end_ts, cid in cycle_pairs if end_ts <= ts]
    if prior:
        end_ts, cid = prior[-1]
        delta = int((ts - end_ts).total_seconds())
        if delta <= past_slack_seconds:
            return (cid, "previous_cycle_end", -delta)

    return ("", "unresolved", -1)


def loads_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except json.JSONDecodeError:
        return []


def loads_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


def derive_state(mode: str, routing_focus: str, body_state: str) -> str:
    m = (mode or "").lower()
    rf = (routing_focus or "").lower()
    bs = (body_state or "").lower()
    if m in {"rest", "sleep"} or rf == "rest" or bs == "resting":
        return "sleep"
    if m in {"idle", "ambient"} or rf in {"idle", "news"}:
        return "idle"
    return "active"


def classify_action_type(action: str) -> str:
    a = (action or "").lower()
    if a in {"speak", "tg_send", "reply_x"}:
        return "chat_reply"
    if a == "post_x":
        return "x_post"
    if a in {"browse_web", "read_content", "save_for_later", "mention_in_conversation"}:
        return "web_browse"
    if a in {"post_x_image", "tg_send_image"}:
        return "media_gen"
    return a


def classify_channel(action: str, target: str | None) -> str:
    a = (action or "").lower()
    if a in {"post_x", "reply_x", "post_x_image", "post_x_draft"}:
        return "x"
    if a.startswith("x_") or a.endswith("_x"):
        return "x"
    if a.startswith("tg_") or a.startswith("tg"):
        return "telegram"
    if a in {"browse_web", "read_content", "save_for_later", "mention_in_conversation"}:
        return "web"
    if a == "speak":
        return "chat"
    if target:
        t = target.lower()
        if "visitor" in t:
            return "chat"
        if "x" in t:
            return "x"
    return "internal"


def infer_sleep_or_awake(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    hour_jst = dt.astimezone(timezone(timedelta(hours=9))).hour
    return "sleep" if 3 <= hour_jst < 6 else "awake"


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        if JSON_HEADER:
            f.write(json.dumps({"_metadata": JSON_HEADER}, ensure_ascii=True) + "\n")
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = obj
    if JSON_HEADER and isinstance(obj, dict) and "_metadata" not in obj:
        payload = {"_metadata": JSON_HEADER, **obj}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def resolve_run_metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    """Resolve strict run metadata used in all JSON artifact headers."""
    run_row = None
    try:
        run_row = conn.execute(
            """SELECT run_id, model_name, commit_hash, config_hash, seed,
                      started_at_utc, ended_at_utc, status
               FROM run_registry
               ORDER BY started_at_utc DESC
               LIMIT 1"""
        ).fetchone()
    except sqlite3.Error:
        run_row = None

    llm_row = conn.execute(
        """SELECT run_id, model, created_at
           FROM llm_call_log
           WHERE COALESCE(run_id, '') != ''
           ORDER BY created_at DESC
           LIMIT 1"""
    ).fetchone()

    run_id = (run_row["run_id"] if run_row else None) or (llm_row["run_id"] if llm_row else "")
    model_name = (run_row["model_name"] if run_row else "") or (llm_row["model"] if llm_row else "")
    commit_hash = run_row["commit_hash"] if run_row else ""
    config_hash = run_row["config_hash"] if run_row else ""
    seed = run_row["seed"] if run_row else None
    return {
        "model_name": model_name or "",
        "git_commit": commit_hash or "",
        "commit_hash": commit_hash or "",
        "config_hash": config_hash or "",
        "seed": seed,
        "timestamp": iso_utc(datetime.now(UTC)),
        "run_id": run_id or "",
    }


def get_fix_commit_time(repo: Path, commit: str) -> str:
    import subprocess

    try:
        out = subprocess.check_output(
            ["git", "show", "-s", "--date=iso", "--format=%ad", commit],
            cwd=repo,
            text=True,
        ).strip()
        return out
    except Exception:
        return ""


def export_pack(db_path: Path, repo_root: Path, out_root: Path) -> Path:
    global JSON_HEADER
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    llm_all = conn.execute(
        """SELECT id, COALESCE(timestamp_utc, created_at) AS timestamp_utc, created_at,
                  provider, model, purpose, call_site, stage, cycle_id, run_id,
                  prompt_tokens, completion_tokens, total_tokens,
                  input_tokens, output_tokens, cost_usd, latency_ms,
                  success, error_type, request_id, input_hash, output_hash
           FROM llm_call_log
           ORDER BY created_at"""
    ).fetchall()
    if not llm_all:
        raise RuntimeError("No llm_call_log rows found in DB.")

    llm_ts = [parse_ts(r["timestamp_utc"] or r["created_at"]) for r in llm_all]
    llm_ts = [t for t in llm_ts if t is not None]
    end_ts = max(llm_ts)
    start_ts = end_ts - timedelta(days=7)

    window_label = f"{start_ts.date().isoformat()}_to_{end_ts.date().isoformat()}_utc"
    bundle_dir = out_root / f"alive_evidence_pack_{window_label}"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    run_metadata = resolve_run_metadata(conn)
    JSON_HEADER = run_metadata

    # 1) llm_calls.csv
    llm_rows: list[dict[str, Any]] = []
    for r in llm_all:
        ts = parse_ts(r["timestamp_utc"] or r["created_at"])
        if not in_window(ts, start_ts, end_ts):
            continue
        in_tok = int(r["prompt_tokens"] if r["prompt_tokens"] is not None else (r["input_tokens"] or 0))
        out_tok = int(r["completion_tokens"] if r["completion_tokens"] is not None else (r["output_tokens"] or 0))
        total_tok = int(r["total_tokens"] if r["total_tokens"] is not None else (in_tok + out_tok))
        llm_rows.append(
            {
                "timestamp_utc": iso_utc(ts),
                "model": r["model"] or "",
                "prompt_tokens": in_tok,
                "completion_tokens": out_tok,
                "total_tokens": total_tok,
                "cost_usd": float(r["cost_usd"] or 0.0),
                "purpose_stage": (r["stage"] or r["call_site"] or r["purpose"] or ""),
                "cycle_id": r["cycle_id"] or "",
                "run_id": r["run_id"] or "",
                "provider": r["provider"] or "",
                "latency_ms": int(r["latency_ms"] or 0),
                "success": int(r["success"]) if r["success"] is not None else 1,
                "error_type": r["error_type"] or "",
                "request_id": r["request_id"] or "",
                "input_hash": r["input_hash"] or "",
                "output_hash": r["output_hash"] or "",
                "call_id": r["id"] or "",
            }
        )
    write_csv(bundle_dir / "llm_calls.csv", llm_rows)

    # 2) cycles.csv
    cycle_all = conn.execute(
        """SELECT id, ts, mode, focus_type, routing_focus, token_budget, memory_count,
                  dropped, internal_monologue, dialogue, body_state, drives,
                  run_id, budget_usd_daily_cap, budget_spent_usd_today,
                  budget_remaining_usd_today, budget_mode, governor_decision
           FROM cycle_log
           ORDER BY ts"""
    ).fetchall()
    cycle_filtered: list[sqlite3.Row] = []
    for r in cycle_all:
        ts = parse_ts(r["ts"])
        if in_window(ts, start_ts, end_ts):
            cycle_filtered.append(r)
    cycle_pairs = [
        (parse_ts(r["ts"]), r["id"] or "")
        for r in cycle_filtered
        if parse_ts(r["ts"]) is not None
    ]
    cycle_pairs.sort(key=lambda x: x[0])

    cycle_rows: list[dict[str, Any]] = []
    prev_end: datetime | None = None
    for r in cycle_filtered:
        end = parse_ts(r["ts"])
        start = prev_end or end
        dropped = loads_json_list(r["dropped"])
        stage_decisions = {
            "routing_focus": r["routing_focus"] or "",
            "token_budget": int(r["token_budget"] or 0),
            "memory_count": int(r["memory_count"] or 0),
            "dropped_count": len(dropped),
        }
        monologue = (r["internal_monologue"] or "").lower()
        dialogue = (r["dialogue"] or "").lower()
        err = ""
        for marker in ("error", "failed", "exception"):
            if marker in monologue or marker in dialogue:
                err = marker
                break
        cycle_rows.append(
            {
                "cycle_start_ts_utc": iso_utc(start),
                "cycle_end_ts_utc": iso_utc(end),
                "cycle_id": r["id"] or "",
                "selected_focus": r["focus_type"] or "",
                "router_outcome": r["routing_focus"] or "",
                "stage_decisions": json.dumps(stage_decisions, ensure_ascii=True),
                "success_flag": 0 if (r["mode"] or "").lower() == "error" else 1,
                "error_code": err,
                "sleep_idle_active_state": derive_state(
                    r["mode"] or "", r["routing_focus"] or "", r["body_state"] or ""
                ),
                "mode": r["mode"] or "",
                "memory_count": int(r["memory_count"] or 0),
                "token_budget": int(r["token_budget"] or 0),
                "run_id": r["run_id"] or "",
                "budget_usd_daily_cap": float(r["budget_usd_daily_cap"] or 0.0),
                "budget_spent_usd_today": float(r["budget_spent_usd_today"] or 0.0),
                "budget_remaining_usd_today": float(r["budget_remaining_usd_today"] or 0.0),
                "budget_mode": r["budget_mode"] or "",
                "governor_decision": r["governor_decision"] or "",
                "cycle_duration_s_est": (
                    int((end - start).total_seconds()) if end and start else 0
                ),
            }
        )
        prev_end = end
    write_csv(bundle_dir / "cycles.csv", cycle_rows)

    # 2b) llm_calls_cycle_join_fix.csv
    llm_join_rows: list[dict[str, Any]] = []
    for row in llm_rows:
        ts = parse_ts(row["timestamp_utc"])
        logged_cid = row.get("cycle_id", "") or ""
        if logged_cid:
            resolved_cid, method, delta_s = logged_cid, "logged", 0
        else:
            resolved_cid, method, delta_s = resolve_cycle_id_for_ts(ts, cycle_pairs)
        llm_join_rows.append(
            {
                **row,
                "cycle_id_raw": logged_cid,
                "cycle_id": resolved_cid,
                "cycle_id_resolution": method,
                "cycle_delta_seconds": delta_s,
            }
        )
    write_csv(bundle_dir / "llm_calls_cycle_join_fix.csv", llm_join_rows)

    # 3) actions.csv
    action_all = conn.execute(
        """SELECT id, COALESCE(timestamp_utc, created_at) AS timestamp_utc, created_at,
                  cycle_id, run_id, action, action_type, channel, status, target, target_id, source,
                  suppression_reason, reason, success, error, cooldown_state,
                  rate_limit_remaining, limiter_decision, action_payload_hash
           FROM action_log
           ORDER BY created_at"""
    ).fetchall()
    action_rows: list[dict[str, Any]] = []
    for r in action_all:
        ts = parse_ts(r["timestamp_utc"] or r["created_at"])
        if not in_window(ts, start_ts, end_ts):
            continue
        status = (r["status"] or "").lower()
        action_rows.append(
            {
                "timestamp_utc": iso_utc(ts),
                "action_type": (r["action_type"] or classify_action_type(r["action"] or "")),
                "action_name": r["action"] or "",
                "target_channel": (r["channel"] or classify_channel(r["action"] or "", r["target"])),
                "execution_state": status,
                "executed_vs_suppressed_deferred": (
                    "executed" if status == "executed" else "suppressed_or_deferred"
                ),
                "suppression_reason": (r["suppression_reason"] or r["reason"] or ""),
                "error": r["error"] or "",
                "source": r["source"] or "",
                "cycle_id": r["cycle_id"] or "",
                "run_id": r["run_id"] or "",
                "target_id": r["target_id"] or r["target"] or "",
                "cooldown_state": r["cooldown_state"] or "",
                "rate_limit_remaining": (
                    int(r["rate_limit_remaining"]) if r["rate_limit_remaining"] is not None else ""
                ),
                "limiter_decision": r["limiter_decision"] or "",
                "action_payload_hash": r["action_payload_hash"] or "",
                "action_id": r["id"] or "",
            }
        )
    write_csv(bundle_dir / "actions.csv", action_rows)

    # 4) memory_writes.csv
    memory_rows: list[dict[str, Any]] = []

    journals = conn.execute(
        "SELECT id, created_at, content, tags FROM journal_entries ORDER BY created_at"
    ).fetchall()
    for r in journals:
        ts = parse_ts(r["created_at"])
        if not in_window(ts, start_ts, end_ts):
            continue
        tags = loads_json_list(r["tags"])
        tagset = {str(t).lower() for t in tags}
        source = "sleep" if tagset & {"sleep_reflection", "nap_reflection", "sleep_cycle", "daily", "quiet_day"} else "awake"
        mtype = "summary" if tagset & {"sleep_cycle", "daily", "quiet_day"} else "episodic"
        content = r["content"] or ""
        memory_rows.append(
            {
                "timestamp_utc": iso_utc(ts),
                "memory_type": mtype,
                "size_tokens_est": estimate_tokens(content),
                "size_bytes": len(content.encode("utf-8")),
                "source": source,
                "cycle_id": "",
                "event_table": "journal_entries",
                "event_id": r["id"] or "",
            }
        )

    traits = conn.execute(
        """SELECT id, observed_at, trait_value, source_event_id
           FROM visitor_traits ORDER BY observed_at"""
    ).fetchall()
    for r in traits:
        ts = parse_ts(r["observed_at"])
        if not in_window(ts, start_ts, end_ts):
            continue
        val = r["trait_value"] or ""
        memory_rows.append(
            {
                "timestamp_utc": iso_utc(ts),
                "memory_type": "semantic",
                "size_tokens_est": estimate_tokens(val),
                "size_bytes": len(val.encode("utf-8")),
                "source": infer_sleep_or_awake(ts),
                "cycle_id": "",
                "event_table": "visitor_traits",
                "event_id": r["id"] or "",
            }
        )

    totems = conn.execute(
        "SELECT id, first_seen, entity, context FROM totems ORDER BY first_seen"
    ).fetchall()
    for r in totems:
        ts = parse_ts(r["first_seen"])
        if not in_window(ts, start_ts, end_ts):
            continue
        text = f"{r['entity'] or ''} {r['context'] or ''}".strip()
        memory_rows.append(
            {
                "timestamp_utc": iso_utc(ts),
                "memory_type": "semantic",
                "size_tokens_est": estimate_tokens(text),
                "size_bytes": len(text.encode("utf-8")),
                "source": infer_sleep_or_awake(ts),
                "cycle_id": "",
                "event_table": "totems",
                "event_id": r["id"] or "",
            }
        )

    summaries = conn.execute(
        """SELECT id, date, emotional_arc, notable_totems, created_at
           FROM daily_summaries ORDER BY created_at"""
    ).fetchall()
    for r in summaries:
        ts = parse_ts(r["created_at"]) or parse_ts((r["date"] or "") + "T00:00:00+00:00")
        if not in_window(ts, start_ts, end_ts):
            continue
        text = f"{r['emotional_arc'] or ''} {r['notable_totems'] or ''}".strip()
        memory_rows.append(
            {
                "timestamp_utc": iso_utc(ts),
                "memory_type": "summary",
                "size_tokens_est": estimate_tokens(text),
                "size_bytes": len(text.encode("utf-8")),
                "source": "sleep",
                "cycle_id": "",
                "event_table": "daily_summaries",
                "event_id": r["id"] or "",
            }
        )

    try:
        structured_memory = conn.execute(
            """SELECT timestamp_utc, memory_type, tokens_written, size_bytes,
                      source, cycle_id, location, id, content_hash, fact_id
               FROM memory_write_log
               ORDER BY timestamp_utc"""
        ).fetchall()
        structured_rows: list[dict[str, Any]] = []
        for r in structured_memory:
            ts = parse_ts(r["timestamp_utc"])
            if not in_window(ts, start_ts, end_ts):
                continue
            structured_rows.append(
                {
                    "timestamp_utc": iso_utc(ts),
                    "memory_type": r["memory_type"] or "",
                    "size_tokens_est": int(r["tokens_written"] or 0),
                    "size_bytes": int(r["size_bytes"] or 0),
                    "source": r["source"] or "",
                    "cycle_id": r["cycle_id"] or "",
                    "event_table": r["location"] or "memory_write_log",
                    "event_id": r["id"] or "",
                    "content_hash": r["content_hash"] or "",
                    "fact_id": r["fact_id"] or "",
                }
            )
        if structured_rows:
            memory_rows = structured_rows
    except sqlite3.Error:
        pass

    memory_rows.sort(key=lambda row: row["timestamp_utc"])
    write_csv(bundle_dir / "memory_writes.csv", memory_rows)

    # 4b) delayed_recall_test.csv / .jsonl (heuristic)
    trait_facts = conn.execute(
        """SELECT id, visitor_id, trait_key, trait_value, observed_at
           FROM visitor_traits
           ORDER BY observed_at"""
    ).fetchall()
    speech_events = conn.execute(
        """SELECT id, source, ts, json_extract(payload, '$.text') AS text
           FROM events
           WHERE event_type='visitor_speech'
           ORDER BY ts"""
    ).fetchall()
    convo_rows = conn.execute(
        """SELECT visitor_id, role, text, ts
           FROM conversation_log
           ORDER BY ts"""
    ).fetchall()

    speech_by_visitor: dict[str, list[sqlite3.Row]] = {}
    for ev in speech_events:
        src = ev["source"] or ""
        if not src.startswith("visitor:"):
            continue
        vid = src.split(":", 1)[1]
        speech_by_visitor.setdefault(vid, []).append(ev)

    convo_by_visitor: dict[str, list[sqlite3.Row]] = {}
    for c in convo_rows:
        convo_by_visitor.setdefault(c["visitor_id"], []).append(c)

    delayed_rows: list[dict[str, Any]] = []
    for fact in trait_facts:
        injection_ts = parse_ts(fact["observed_at"])
        if injection_ts is None or not in_window(injection_ts, start_ts, end_ts):
            continue
        vid = fact["visitor_id"] or ""
        fact_tokens = tokenize_words(f"{fact['trait_key'] or ''} {fact['trait_value'] or ''}")
        if not fact_tokens:
            continue

        # Delayed recall probe: prefer first later visitor question after >=5m.
        # Fallback: first later visitor message after >=5m.
        min_delay_ts = injection_ts + timedelta(minutes=5)
        test_event = None
        fallback_event = None
        for ev in speech_by_visitor.get(vid, []):
            test_ts = parse_ts(ev["ts"])
            text = ev["text"] or ""
            if test_ts is None or test_ts <= min_delay_ts:
                continue
            if fallback_event is None:
                fallback_event = ev
            if "?" in text:
                test_event = ev
                break
        if test_event is None:
            test_event = fallback_event
        if test_event is None:
            continue

        test_ts = parse_ts(test_event["ts"])
        best_overlap = 0.0
        for msg in convo_by_visitor.get(vid, []):
            if (msg["role"] or "").lower() != "shopkeeper":
                continue
            msg_ts = parse_ts(msg["ts"])
            if msg_ts is None or test_ts is None:
                continue
            if not (test_ts <= msg_ts <= test_ts + timedelta(minutes=30)):
                continue
            resp_tokens = tokenize_words(msg["text"] or "")
            if not resp_tokens:
                continue
            overlap = len(resp_tokens & fact_tokens) / max(len(fact_tokens), 1)
            if overlap > best_overlap:
                best_overlap = overlap

        retrieved = 1 if best_overlap >= 0.15 else 0
        resolved_cycle_id, _, _ = resolve_cycle_id_for_ts(test_ts, cycle_pairs)
        delayed_rows.append(
            {
                "injection_time_utc": iso_utc(injection_ts),
                "fact_id": fact["id"] or "",
                "content_hash": sha12(fact["trait_value"] or ""),
                "test_time_utc": iso_utc(test_ts),
                "question_id": test_event["id"] or "",
                "retrieved": retrieved,
                "answer_correctness_score": round(best_overlap, 3),
                "cycle_id": resolved_cycle_id,
                "method": "trait_to_later_question_overlap",
            }
        )

    try:
        recall_rows = conn.execute(
            """SELECT t.test_time_utc, t.question_id, t.fact_id, t.retrieved,
                      t.answer_correctness_score, t.used_in_answer, t.cycle_id, t.run_id,
                      i.injection_time_utc, i.content_hash, i.injection_channel
               FROM recall_test_log t
               LEFT JOIN recall_injection_log i
                 ON i.fact_id = t.fact_id AND i.run_id = t.run_id
               ORDER BY t.test_time_utc"""
        ).fetchall()
        structured_delayed: list[dict[str, Any]] = []
        for r in recall_rows:
            test_ts = parse_ts(r["test_time_utc"])
            inj_ts = parse_ts(r["injection_time_utc"])
            if not in_window(test_ts, start_ts, end_ts):
                continue
            structured_delayed.append(
                {
                    "injection_time_utc": iso_utc(inj_ts),
                    "fact_id": r["fact_id"] or "",
                    "content_hash": r["content_hash"] or "",
                    "test_time_utc": iso_utc(test_ts),
                    "question_id": r["question_id"] or "",
                    "retrieved": int(r["retrieved"] or 0),
                    "answer_correctness_score": float(r["answer_correctness_score"] or 0.0),
                    "cycle_id": r["cycle_id"] or "",
                    "run_id": r["run_id"] or "",
                    "used_in_answer": int(r["used_in_answer"]) if r["used_in_answer"] is not None else "",
                    "injection_channel": r["injection_channel"] or "",
                    "method": "structured_recall_tables",
                }
            )
        if structured_delayed:
            delayed_rows = structured_delayed
    except sqlite3.Error:
        pass

    delayed_rows.sort(key=lambda r: r["test_time_utc"])
    write_csv(bundle_dir / "delayed_recall_test.csv", delayed_rows)
    write_jsonl(bundle_dir / "delayed_recall_test.jsonl", delayed_rows)

    # Incidents markdown
    anti_row = conn.execute(
        """SELECT COUNT(*) AS n, MIN(created_at) AS t0, MAX(created_at) AS t1
           FROM threads WHERE lower(title) LIKE '%anti-pleasure%'"""
    ).fetchone()
    tg_spam = conn.execute(
        """SELECT source, COUNT(*) AS c, MIN(ts) AS t0, MAX(ts) AS t1
           FROM events
           WHERE event_type='visitor_connect' AND source LIKE 'visitor:tg_%'
           GROUP BY source ORDER BY c DESC LIMIT 1"""
    ).fetchone()
    low_val = conn.execute(
        """SELECT COUNT(*) AS c, MIN(ts) AS t0, MAX(ts) AS t1
           FROM cycle_log
           WHERE CAST(json_extract(drives,'$.mood_valence') AS REAL) <= -0.85"""
    ).fetchone()
    ext_err = conn.execute(
        """SELECT error, MIN(timestamp) AS t0, MAX(timestamp) AS t1, COUNT(*) AS c
           FROM external_action_log
           WHERE error IS NOT NULL AND error != ''
           GROUP BY error ORDER BY c DESC LIMIT 1"""
    ).fetchone()

    commit_map = {
        "f9683ed": "HOTFIX-001/002/003 — rate limit backoff, valence floor, thread dedup",
        "57a3ae8": "HOTFIX-003 thread dedup + rumination breaker",
        "dfdedcc": "HOTFIX-005 visitor registration across entry points",
    }
    commit_times = {
        c: get_fix_commit_time(repo_root, c)
        for c in commit_map
    }

    incidents_md = [
        "# Incident + Fix Timeline (7-day window)",
        "",
        f"- Window UTC: `{iso_utc(start_ts)}` to `{iso_utc(end_ts)}`",
        f"- Source DB: `{db_path}`",
        "",
        "## 1) Valence death-spiral risk",
        f"- Incident start: `{low_val['t0'] if low_val and low_val['t0'] else ''}`",
        f"- Incident end: `{low_val['t1'] if low_val and low_val['t1'] else ''}`",
        f"- Symptom: `{int(low_val['c']) if low_val and low_val['c'] else 0}` cycles with mood_valence <= -0.85",
        "- Root cause: cortex mood output could overpower homeostatic recovery; no hard floor/circuit-breaker.",
        f"- Fix commit: `f9683ed` ({commit_map['f9683ed']}) at `{commit_times['f9683ed']}`",
        "- State continuity preserved: yes (same DB state carried across fix period).",
        "",
        "## 2) Thread rumination / duplicate topic loop",
        f"- Incident start: `{anti_row['t0'] if anti_row and anti_row['t0'] else ''}`",
        f"- Incident end: `{anti_row['t1'] if anti_row and anti_row['t1'] else ''}`",
        f"- Symptom: `{int(anti_row['n']) if anti_row and anti_row['n'] else 0}` anti-pleasure-thread creations in the window",
        "- Root cause: missing dedup + no rumination breaker in thread/context selection.",
        f"- Fix commit(s): `57a3ae8` ({commit_map['57a3ae8']}) at `{commit_times['57a3ae8']}`, plus `f9683ed`.",
        "- State continuity preserved: yes (threads retained; fix changed selection/creation behavior).",
        "",
        "## 3) Visitor connect/boundary spam (Telegram race)",
        f"- Incident start: `{tg_spam['t0'] if tg_spam and tg_spam['t0'] else ''}`",
        f"- Incident end: `{tg_spam['t1'] if tg_spam and tg_spam['t1'] else ''}`",
        (
            f"- Symptom: `{int(tg_spam['c']) if tg_spam and tg_spam['c'] else 0}` "
            f"`visitor_connect` events for `{tg_spam['source'] if tg_spam and tg_spam['source'] else ''}`"
        ),
        "- Root cause: connect/session-boundary race on repeated messages from same visitor.",
        f"- Fix commit: `dfdedcc` ({commit_map['dfdedcc']}) at `{commit_times['dfdedcc']}`",
        "- State continuity preserved: yes (visitor records persisted; connect signaling corrected).",
        "",
        "## 4) External action error (web parser contract mismatch)",
        f"- Incident start: `{ext_err['t0'] if ext_err and ext_err['t0'] else ''}`",
        f"- Incident end: `{ext_err['t1'] if ext_err and ext_err['t1'] else ''}`",
        f"- Symptom: `{ext_err['error'] if ext_err and ext_err['error'] else ''}`",
        "- Root cause: response shape mismatch while parsing external web call response.",
        "- Fix: parser hardening in body/web execution path (description-level fix; no unique incident-tagged hash in this snapshot).",
        "- State continuity preserved: yes (error isolated to action execution; core memory/state continued).",
        "",
    ]
    (bundle_dir / "incidents.md").write_text("\n".join(incidents_md), encoding="utf-8")

    # Config snapshot
    run_cfg = bundle_dir / "run_config"
    copy_if_exists(repo_root / "prompt" / "budget_config.json", run_cfg / "static" / "budget_config.json")
    copy_if_exists(repo_root / "risk-policy.json", run_cfg / "static" / "risk-policy.json")
    copy_if_exists(repo_root / "scope-check.sh", run_cfg / "static" / "scope-check.sh")
    copy_if_exists(repo_root / "llm" / "config.py", run_cfg / "static" / "llm_config.py")
    copy_if_exists(repo_root / "body" / "rate_limiter.py", run_cfg / "static" / "rate_limiter.py")
    copy_if_exists(repo_root / "pipeline" / "basal_ganglia.py", run_cfg / "static" / "basal_ganglia.py")
    copy_if_exists(repo_root / "pipeline" / "validator.py", run_cfg / "static" / "validator.py")
    copy_if_exists(repo_root / "pipeline" / "action_registry.py", run_cfg / "static" / "action_registry.py")

    settings = conn.execute("SELECT key, value, updated_at FROM settings ORDER BY key").fetchall()
    settings_rows = [
        {"key": r["key"], "value": r["value"], "updated_at": r["updated_at"] or ""}
        for r in settings
    ]
    write_csv(run_cfg / "runtime" / "settings.csv", settings_rows)

    params = conn.execute(
        "SELECT key, value, modified_at, description FROM self_parameters ORDER BY key"
    ).fetchall()
    params_rows = [
        {
            "key": r["key"],
            "value": r["value"],
            "modified_at": r["modified_at"] or "",
            "description": r["description"] or "",
        }
        for r in params
    ]
    write_csv(run_cfg / "runtime" / "self_parameters.csv", params_rows)

    channels = conn.execute(
        "SELECT channel_name, enabled, disabled_at, disabled_by FROM channel_config ORDER BY channel_name"
    ).fetchall()
    channel_rows = [
        {
            "channel_name": r["channel_name"],
            "enabled": int(r["enabled"] or 0),
            "disabled_at": r["disabled_at"] or "",
            "disabled_by": r["disabled_by"] or "",
        }
        for r in channels
    ]
    write_csv(run_cfg / "runtime" / "channel_config.csv", channel_rows)

    observed_model = conn.execute(
        """SELECT COALESCE(call_site, purpose) AS call_site, model,
                  COUNT(*) AS calls,
                  SUM(COALESCE(cost_usd, 0.0)) AS cost_usd
           FROM llm_call_log
           GROUP BY COALESCE(call_site, purpose), model
           ORDER BY calls DESC"""
    ).fetchall()
    observed_rows = [
        {
            "call_site": r["call_site"] or "",
            "model": r["model"] or "",
            "calls": int(r["calls"] or 0),
            "cost_usd": round(float(r["cost_usd"] or 0.0), 6),
        }
        for r in observed_model
    ]
    write_csv(run_cfg / "runtime" / "observed_model_routing.csv", observed_rows)

    # Golden examples
    cycle_meta = {
        r["id"]: {
            "cycle_end_ts_utc": iso_utc(parse_ts(r["ts"])),
            "mode": r["mode"] or "",
            "focus_type": r["focus_type"] or "",
            "routing_focus": r["routing_focus"] or "",
            "memory_count": int(r["memory_count"] or 0),
        }
        for r in cycle_filtered
    }
    executed_by_cycle: dict[str, list[str]] = {}
    for r in action_rows:
        if r["execution_state"] == "executed":
            executed_by_cycle.setdefault(r["cycle_id"], []).append(r["action_name"])

    # 10 real-action cycles
    outward_actions = {"speak", "reply_x", "tg_send", "post_x", "post_x_image", "browse_web", "read_content", "tg_send_image"}
    real_examples: list[dict[str, Any]] = []
    seen_cycles: set[str] = set()
    for r in action_rows:
        if r["execution_state"] != "executed":
            continue
        if r["action_name"] not in outward_actions:
            continue
        cid = r["cycle_id"]
        if cid in seen_cycles:
            continue
        seen_cycles.add(cid)
        meta = cycle_meta.get(cid, {})
        real_examples.append(
            {
                "cycle_id": cid,
                "timestamp_utc": meta.get("cycle_end_ts_utc", r["timestamp_utc"]),
                "mode": meta.get("mode", ""),
                "routing_focus": meta.get("routing_focus", ""),
                "focus_type": meta.get("focus_type", ""),
                "memory_count": meta.get("memory_count", 0),
                "executed_actions": executed_by_cycle.get(cid, []),
                "channels": sorted({classify_channel(a, None) for a in executed_by_cycle.get(cid, [])}),
            }
        )
        if len(real_examples) >= 10:
            break
    write_jsonl(bundle_dir / "golden_examples" / "real_actions_10.jsonl", real_examples)

    # 10 suppressed/deferred examples
    suppressed_examples: list[dict[str, Any]] = []
    for r in action_rows:
        if r["execution_state"] not in {"suppressed", "deferred", "inhibited", "incapable"}:
            continue
        meta = cycle_meta.get(r["cycle_id"], {})
        suppressed_examples.append(
            {
                "timestamp_utc": r["timestamp_utc"],
                "cycle_id": r["cycle_id"],
                "mode": meta.get("mode", ""),
                "routing_focus": meta.get("routing_focus", ""),
                "action_name": r["action_name"],
                "execution_state": r["execution_state"],
                "suppression_reason": r["suppression_reason"],
            }
        )
        if len(suppressed_examples) >= 10:
            break
    write_jsonl(bundle_dir / "golden_examples" / "suppressed_10.jsonl", suppressed_examples)

    # 10 memory-recall before/after proxies
    cycle_ids_sorted = [r["id"] for r in cycle_filtered]
    recall_examples: list[dict[str, Any]] = []
    for i in range(1, len(cycle_ids_sorted)):
        after_id = cycle_ids_sorted[i]
        before_id = cycle_ids_sorted[i - 1]
        after_meta = cycle_meta.get(after_id, {})
        before_meta = cycle_meta.get(before_id, {})
        if int(after_meta.get("memory_count", 0)) <= 0:
            continue
        after_actions = executed_by_cycle.get(after_id, [])
        if not after_actions:
            continue
        before_actions = executed_by_cycle.get(before_id, [])
        recall_examples.append(
            {
                "before_cycle_id": before_id,
                "before_ts_utc": before_meta.get("cycle_end_ts_utc", ""),
                "before_memory_count": before_meta.get("memory_count", 0),
                "before_actions": before_actions,
                "after_cycle_id": after_id,
                "after_ts_utc": after_meta.get("cycle_end_ts_utc", ""),
                "after_memory_count": after_meta.get("memory_count", 0),
                "after_actions": after_actions,
                "after_focus": after_meta.get("focus_type", ""),
                "action_profile_changed": sorted(before_actions) != sorted(after_actions),
            }
        )
        if len(recall_examples) >= 10:
            break
    write_jsonl(bundle_dir / "golden_examples" / "memory_recall_before_after_10.jsonl", recall_examples)

    # Optional: continuity + safety
    continuity_rows: list[dict[str, Any]] = []
    for r in cycle_filtered:
        drives = loads_json_dict(r["drives"])
        continuity_rows.append(
            {
                "timestamp_utc": iso_utc(parse_ts(r["ts"])),
                "cycle_id": r["id"] or "",
                "mode": r["mode"] or "",
                "mood_valence": drives.get("mood_valence", ""),
                "mood_arousal": drives.get("mood_arousal", ""),
                "social_hunger": drives.get("social_hunger", ""),
                "curiosity": drives.get("curiosity", ""),
                "expression_need": drives.get("expression_need", ""),
                "rest_need": drives.get("rest_need", ""),
                "energy": drives.get("energy", ""),
                "drives_hash": sha12(json.dumps(drives, sort_keys=True)),
            }
        )
    write_csv(bundle_dir / "optional" / "state_continuity.csv", continuity_rows)

    reason_counts: dict[str, int] = {}
    for r in action_rows:
        reason = (r["suppression_reason"] or "").strip()
        if not reason:
            continue
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    top_reasons = sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)[:12]
    safety_md = [
        "# Safety / Abuse Handling Examples",
        "",
        "## Top suppression reasons (from action_log)",
        "",
    ]
    for reason, cnt in top_reasons:
        safety_md.append(f"- {cnt}x `{reason}`")
    safety_md.extend(
        [
            "",
            "## Hard gates present in config/code snapshot",
            "",
            "- `pipeline/gates.py`: strips forbidden raw URL features before cortex context.",
            "- `pipeline/validator.py`: disclosure/engagement/physics/entropy gates.",
            "- `body/rate_limiter.py`: channel kill switches + cooldown/hour/day caps.",
            "- `pipeline/basal_ganglia.py`: inhibition gate + explicit suppression reasons in motor plan.",
            "",
        ]
    )
    (bundle_dir / "optional" / "safety_examples.md").write_text("\n".join(safety_md), encoding="utf-8")

    # Bundle metadata
    meta = {
        "window_start_utc": iso_utc(start_ts),
        "window_end_utc": iso_utc(end_ts),
        "source_db": str(db_path),
        "run": {
            "run_id": run_metadata.get("run_id", ""),
            "model_name": run_metadata.get("model_name", ""),
            "commit_hash": run_metadata.get("commit_hash", ""),
            "config_hash": run_metadata.get("config_hash", ""),
            "seed": run_metadata.get("seed"),
        },
        "row_counts": {
            "llm_calls": len(llm_rows),
            "llm_calls_cycle_join_fix": len(llm_join_rows),
            "cycles": len(cycle_rows),
            "actions": len(action_rows),
            "memory_writes": len(memory_rows),
            "delayed_recall_tests": len(delayed_rows),
            "golden_real_actions": len(real_examples),
            "golden_suppressed": len(suppressed_examples),
            "golden_memory_recall": len(recall_examples),
        },
    }
    write_json(bundle_dir / "bundle_meta.json", meta)
    write_json(bundle_dir / "run_metadata.json", run_metadata)

    # Zip
    zip_base = out_root / f"alive_evidence_pack_{window_label}"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=bundle_dir)
    return Path(zip_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export 7-day evidence pack.")
    parser.add_argument(
        "--db",
        default="data/prod_snapshot_20260220_1551.db",
        help="Path to SQLite DB snapshot (read-only).",
    )
    parser.add_argument(
        "--out",
        default="outputs",
        help="Output directory for evidence pack and zip.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    db_path = (repo_root / args.db).resolve()
    out_root = (repo_root / args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    zip_path = export_pack(db_path=db_path, repo_root=repo_root, out_root=out_root)
    print(f"EVIDENCE_ZIP={zip_path}")


if __name__ == "__main__":
    main()
