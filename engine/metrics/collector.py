"""Metric collector — computes and stores liveness metrics (TASK-071).

Phase 1 (hourly): M1 uptime, M2 initiative, M7 emotional range.
Phase 2 (hourly): M3 entropy. (6-hourly): M4 knowledge, M5 recall, M9 unprompted memories.
Stores snapshots in metrics_snapshots table.
"""

import json
from metrics.models import MetricResult, MetricSnapshot
from metrics import m_uptime, m_initiative, m_emotion
from metrics import m_entropy, m_knowledge, m_recall, m_memory
import clock
import db.connection as _connection


# ── Compute ──

async def collect_hourly() -> MetricSnapshot:
    """Compute hourly metrics (Phase 1 + Phase 2 hourly) and store snapshots."""
    ts = clock.now_utc().isoformat()
    results: list[MetricResult] = []

    # Phase 1 hourly
    try:
        results.append(await m_uptime.compute())
    except Exception as e:
        print(f"  [Metrics] M1 (uptime) error: {e}")

    try:
        results.append(await m_initiative.compute(hours=24))
    except Exception as e:
        print(f"  [Metrics] M2 (initiative) error: {e}")

    try:
        results.append(await m_emotion.compute())
    except Exception as e:
        print(f"  [Metrics] M7 (emotion) error: {e}")

    # Phase 2 hourly
    try:
        results.append(await m_entropy.compute(hours=24))
    except Exception as e:
        print(f"  [Metrics] M3 (entropy) error: {e}")

    snapshot = MetricSnapshot(timestamp=ts, period='hourly', metrics=results)

    # Store each metric
    for m in results:
        await _store_snapshot(ts, m.name, m.value, m.details, 'hourly')

    return snapshot


async def collect_six_hourly() -> MetricSnapshot:
    """Compute 6-hourly metrics (Phase 2 knowledge, recall, memory)."""
    ts = clock.now_utc().isoformat()
    results: list[MetricResult] = []

    try:
        results.append(await m_knowledge.compute())
    except Exception as e:
        print(f"  [Metrics] M4 (knowledge) error: {e}")

    try:
        results.append(await m_recall.compute())
    except Exception as e:
        print(f"  [Metrics] M5 (recall) error: {e}")

    try:
        results.append(await m_memory.compute(hours=24))
    except Exception as e:
        print(f"  [Metrics] M9 (memory) error: {e}")

    snapshot = MetricSnapshot(timestamp=ts, period='six_hourly', metrics=results)

    for m in results:
        await _store_snapshot(ts, m.name, m.value, m.details, 'six_hourly')

    return snapshot


async def collect_all() -> MetricSnapshot:
    """Compute all metrics on demand (for API requests)."""
    ts = clock.now_utc().isoformat()
    results: list[MetricResult] = []

    # Phase 1
    try:
        results.append(await m_uptime.compute())
    except Exception as e:
        print(f"  [Metrics] M1 error: {e}")

    try:
        results.append(await m_initiative.compute(hours=24))
    except Exception as e:
        print(f"  [Metrics] M2 error: {e}")

    try:
        results.append(await m_emotion.compute())
    except Exception as e:
        print(f"  [Metrics] M7 error: {e}")

    # Phase 2
    try:
        results.append(await m_entropy.compute(hours=24))
    except Exception as e:
        print(f"  [Metrics] M3 error: {e}")

    try:
        results.append(await m_knowledge.compute())
    except Exception as e:
        print(f"  [Metrics] M4 error: {e}")

    try:
        results.append(await m_recall.compute())
    except Exception as e:
        print(f"  [Metrics] M5 error: {e}")

    try:
        results.append(await m_memory.compute(hours=24))
    except Exception as e:
        print(f"  [Metrics] M9 error: {e}")

    return MetricSnapshot(timestamp=ts, period='snapshot', metrics=results)


# ── Storage ──

async def _store_snapshot(timestamp: str, metric_name: str, value: float,
                          details: dict, period: str) -> None:
    """Insert a metric snapshot into the DB."""
    await _connection._exec_write(
        """INSERT INTO metrics_snapshots (timestamp, metric_name, value, details, period)
           VALUES (?, ?, ?, ?, ?)""",
        (timestamp, metric_name, value, json.dumps(details), period),
    )


# ── Retrieval ──

async def get_latest_snapshot(metric_name: str) -> dict | None:
    """Get the most recent snapshot for a metric."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT timestamp, metric_name, value, details, period
           FROM metrics_snapshots
           WHERE metric_name = ?
           ORDER BY timestamp DESC
           LIMIT 1""",
        (metric_name,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return {
        'timestamp': row['timestamp'],
        'metric_name': row['metric_name'],
        'value': row['value'],
        'details': json.loads(row['details']) if row['details'] else {},
        'period': row['period'],
    }


async def get_metric_trend(metric_name: str, days: int = 30,
                           period: str = 'hourly') -> list[dict]:
    """Get time-series trend data for a metric."""
    from datetime import timedelta
    cutoff = (clock.now_utc() - timedelta(days=days)).isoformat()
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT timestamp, value, details
           FROM metrics_snapshots
           WHERE metric_name = ? AND period = ? AND timestamp >= ?
           ORDER BY timestamp ASC""",
        (metric_name, period, cutoff),
    )
    rows = await cursor.fetchall()
    return [
        {
            'timestamp': r['timestamp'],
            'value': r['value'],
            'details': json.loads(r['details']) if r['details'] else {},
        }
        for r in rows
    ]
