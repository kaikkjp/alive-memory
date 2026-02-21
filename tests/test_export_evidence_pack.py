"""Smoke test for scripts/export_evidence_pack.py."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from scripts.export_evidence_pack import export_pack


def _create_minimal_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()

    cur.execute(
        """CREATE TABLE llm_call_log (
            id TEXT,
            timestamp_utc TEXT,
            created_at TEXT,
            provider TEXT,
            model TEXT,
            purpose TEXT,
            call_site TEXT,
            stage TEXT,
            cycle_id TEXT,
            run_id TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            latency_ms INTEGER,
            success INTEGER,
            error_type TEXT,
            request_id TEXT,
            input_hash TEXT,
            output_hash TEXT
        )"""
    )
    cur.execute(
        """INSERT INTO llm_call_log VALUES (
            'llm1','2026-02-20T00:00:00+00:00','2026-02-20T00:00:00+00:00',
            'openrouter','openai/gpt-4o-mini','cortex','cortex','cortex',
            'cycle-1','run-1',10,5,15,10,5,0.001,120,1,'','','',''
        )"""
    )

    cur.execute(
        """CREATE TABLE cycle_log (
            id TEXT,
            ts TEXT,
            mode TEXT,
            focus_type TEXT,
            routing_focus TEXT,
            token_budget INTEGER,
            memory_count INTEGER,
            dropped TEXT,
            internal_monologue TEXT,
            dialogue TEXT,
            body_state TEXT,
            drives TEXT,
            run_id TEXT,
            budget_usd_daily_cap REAL,
            budget_spent_usd_today REAL,
            budget_remaining_usd_today REAL,
            budget_mode TEXT,
            governor_decision TEXT
        )"""
    )
    cur.execute(
        """INSERT INTO cycle_log VALUES (
            'cycle-1','2026-02-20T00:00:30+00:00','engage','visitor','engage',
            4000,2,'[]','thinking','hello','active',
            '{"mood_valence":0.2,"mood_arousal":0.3,"social_hunger":0.4,"curiosity":0.5,"expression_need":0.2,"rest_need":0.1,"energy":0.8}',
            'run-1',1.0,0.1,0.9,'normal','{"allowed_llm_calls": 1}'
        )"""
    )

    cur.execute(
        """CREATE TABLE action_log (
            id TEXT,
            timestamp_utc TEXT,
            created_at TEXT,
            cycle_id TEXT,
            run_id TEXT,
            action TEXT,
            action_type TEXT,
            channel TEXT,
            status TEXT,
            target TEXT,
            target_id TEXT,
            source TEXT,
            suppression_reason TEXT,
            reason TEXT,
            success INTEGER,
            error TEXT,
            cooldown_state TEXT,
            rate_limit_remaining INTEGER,
            limiter_decision TEXT,
            action_payload_hash TEXT
        )"""
    )
    cur.execute(
        """INSERT INTO action_log VALUES (
            'act-1','2026-02-20T00:00:31+00:00','2026-02-20T00:00:31+00:00',
            'cycle-1','run-1','speak','chat_reply','chat','executed',
            'visitor:tg_1','tg_1','cortex','','',1,'','ready',3,'allow','abc123'
        )"""
    )

    cur.execute("CREATE TABLE journal_entries (id TEXT, created_at TEXT, content TEXT, tags TEXT)")
    cur.execute(
        """INSERT INTO journal_entries VALUES (
            'j1','2026-02-20T00:00:10+00:00','short note','["daily"]'
        )"""
    )

    cur.execute(
        """CREATE TABLE visitor_traits (
            id TEXT,
            visitor_id TEXT,
            trait_key TEXT,
            trait_value TEXT,
            observed_at TEXT,
            source_event_id TEXT
        )"""
    )
    cur.execute(
        """INSERT INTO visitor_traits VALUES (
            'fact-1','tg_1','favorite_band','nujabes','2026-02-20T00:00:00+00:00','evt-0'
        )"""
    )

    cur.execute("CREATE TABLE totems (id TEXT, first_seen TEXT, entity TEXT, context TEXT)")
    cur.execute(
        """INSERT INTO totems VALUES (
            't1','2026-02-20T00:00:05+00:00','rain photo','gift'
        )"""
    )

    cur.execute(
        """CREATE TABLE daily_summaries (
            id TEXT,
            date TEXT,
            emotional_arc TEXT,
            notable_totems TEXT,
            created_at TEXT
        )"""
    )
    cur.execute(
        """INSERT INTO daily_summaries VALUES (
            'd1','2026-02-20','steady','["rain photo"]','2026-02-20T00:00:20+00:00'
        )"""
    )

    cur.execute(
        """CREATE TABLE events (
            id TEXT,
            source TEXT,
            ts TEXT,
            event_type TEXT,
            payload TEXT
        )"""
    )
    cur.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
        (
            "evt-1",
            "visitor:tg_1",
            "2026-02-20T00:10:00+00:00",
            "visitor_speech",
            json.dumps({"text": "What band do I like?"}),
        ),
    )
    cur.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
        (
            "evt-2",
            "visitor:tg_1",
            "2026-02-20T00:00:00+00:00",
            "visitor_connect",
            "{}",
        ),
    )

    cur.execute(
        """CREATE TABLE conversation_log (
            visitor_id TEXT,
            role TEXT,
            text TEXT,
            ts TEXT
        )"""
    )
    cur.execute(
        """INSERT INTO conversation_log VALUES (
            'tg_1','shopkeeper','You told me it was Nujabes.','2026-02-20T00:10:30+00:00'
        )"""
    )

    cur.execute("CREATE TABLE threads (title TEXT, created_at TEXT)")
    cur.execute("INSERT INTO threads VALUES ('anti-pleasure idea','2026-02-20T00:00:00+00:00')")

    cur.execute("CREATE TABLE external_action_log (error TEXT, timestamp TEXT)")
    cur.execute(
        """INSERT INTO external_action_log VALUES (
            'web parser mismatch','2026-02-20T00:00:00+00:00'
        )"""
    )

    cur.execute("CREATE TABLE settings (key TEXT, value TEXT, updated_at TEXT)")
    cur.execute("INSERT INTO settings VALUES ('daily_budget','1.0','2026-02-20T00:00:00+00:00')")

    cur.execute(
        """CREATE TABLE self_parameters (
            key TEXT,
            value TEXT,
            modified_at TEXT,
            description TEXT
        )"""
    )
    cur.execute(
        "INSERT INTO self_parameters VALUES ('output.drives.success_bonus_base','0.02','2026-02-20T00:00:00+00:00','test')"
    )

    cur.execute(
        """CREATE TABLE channel_config (
            channel_name TEXT,
            enabled INTEGER,
            disabled_at TEXT,
            disabled_by TEXT
        )"""
    )
    cur.execute("INSERT INTO channel_config VALUES ('telegram',1,'','')")

    conn.commit()
    conn.close()


def test_export_evidence_pack_smoke(tmp_path: Path) -> None:
    db_path = tmp_path / "mini.db"
    _create_minimal_db(db_path)

    repo_root = Path(__file__).resolve().parents[1]
    zip_path = export_pack(db_path=db_path, repo_root=repo_root, out_root=tmp_path)

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert any(name.endswith("llm_calls.csv") for name in names)
        assert any(name.endswith("actions.csv") for name in names)
        assert any(name.endswith("run_metadata.json") for name in names)
        assert any(name.endswith("bundle_meta.json") for name in names)
