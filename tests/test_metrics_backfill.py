"""Tests for metrics backfill (TASK-071 Phase 1)."""

import json
import pytest
import db
import clock
from metrics.backfill import backfill_all


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    """Use a temp database for each test, with singleton rows seeded."""
    db._db = None
    original_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "test.db")
    await db.init_db()
    yield
    await db.close_db()
    db.DB_PATH = original_path


async def _insert_cycle(cycle_id: str, mode: str = 'ambient',
                         drives: dict = None, ts: str = None):
    """Insert a cycle_log row."""
    d = drives or {'mood_valence': 0.0, 'mood_arousal': 0.3, 'energy': 0.8}
    timestamp = ts or clock.now_utc().isoformat()
    await db._exec_write(
        """INSERT INTO cycle_log (id, mode, drives, ts)
           VALUES (?, ?, ?, ?)""",
        (cycle_id, mode, json.dumps(d), timestamp),
    )


async def _insert_action(cycle_id: str, action: str = 'journal_write',
                          status: str = 'executed', created_at: str = None):
    """Insert an action_log row."""
    import uuid
    action_id = str(uuid.uuid4())[:12]
    ts = created_at or clock.now_utc().isoformat()
    await db._exec_write(
        """INSERT INTO action_log (id, cycle_id, action, status, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (action_id, cycle_id, action, status, 'cortex', ts),
    )


class TestBackfill:

    @pytest.mark.asyncio
    async def test_backfill_empty_db(self):
        result = await backfill_all()
        assert result['status'] == 'empty'

    @pytest.mark.asyncio
    async def test_backfill_creates_daily_snapshots(self):
        ts = '2026-01-15T10:00:00+00:00'
        await _insert_cycle('c1', mode='ambient', ts=ts)
        await _insert_action('c1', created_at=ts)

        result = await backfill_all()
        assert result['status'] == 'completed'
        assert result['days_processed'] >= 1
        assert result['snapshots_written'] >= 1

        # Verify snapshots were stored
        conn = await db.get_db()
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM metrics_snapshots WHERE period = 'daily'"
        )
        row = await cursor.fetchone()
        assert row['cnt'] > 0

    @pytest.mark.asyncio
    async def test_backfill_idempotent(self):
        """Running backfill twice should skip on second run."""
        await _insert_cycle('c1', ts='2026-01-15T10:00:00+00:00')
        result1 = await backfill_all()
        assert result1['status'] == 'completed'

        result2 = await backfill_all()
        assert result2['status'] == 'skipped'

    @pytest.mark.asyncio
    async def test_backfill_multi_day(self):
        """Backfill across multiple days creates snapshots per day."""
        await _insert_cycle('c1', ts='2026-01-10T10:00:00+00:00')
        await _insert_cycle('c2', ts='2026-01-11T10:00:00+00:00')
        await _insert_cycle('c3', ts='2026-01-12T10:00:00+00:00')

        result = await backfill_all()
        assert result['status'] == 'completed'
        assert result['days_processed'] >= 3

        # Check uptime snapshots show increasing cycle counts
        conn = await db.get_db()
        cursor = await conn.execute(
            """SELECT value FROM metrics_snapshots
               WHERE metric_name = 'uptime' AND period = 'daily'
               ORDER BY timestamp ASC"""
        )
        rows = await cursor.fetchall()
        values = [r['value'] for r in rows]
        # Each day should have >= previous day's count
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1]

    @pytest.mark.asyncio
    async def test_backfill_includes_emotion_range(self):
        """Backfill computes emotional range from drives JSON."""
        await _insert_cycle('c1', drives={
            'mood_valence': -0.5, 'mood_arousal': 0.1, 'energy': 0.3,
        }, ts='2026-01-15T10:00:00+00:00')
        await _insert_cycle('c2', drives={
            'mood_valence': 0.8, 'mood_arousal': 0.9, 'energy': 0.9,
        }, ts='2026-01-15T12:00:00+00:00')

        result = await backfill_all()
        assert result['status'] == 'completed'

        conn = await db.get_db()
        cursor = await conn.execute(
            """SELECT value FROM metrics_snapshots
               WHERE metric_name = 'emotional_range' AND period = 'daily'"""
        )
        rows = await cursor.fetchall()
        assert len(rows) > 0
        # Should have at least 2 distinct mood states
        assert rows[-1]['value'] >= 2.0
