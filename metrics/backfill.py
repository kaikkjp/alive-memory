"""Historical backfill — compute metrics retroactively from existing data (TASK-071).

Processes cycle_log and action_log day-by-day, stores daily snapshots so
the metrics dashboard has full history from her first cycle.
"""

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from metrics.models import MetricResult
from metrics.m_emotion import _quantize, _normalize_valence
import db.connection as _connection


async def backfill_all() -> dict:
    """Run full historical backfill. Returns summary of what was computed."""
    conn = await _connection.get_db()

    # Check if we already have backfill data
    cursor = await conn.execute(
        "SELECT COUNT(*) as cnt FROM metrics_snapshots WHERE period = 'daily'"
    )
    row = await cursor.fetchone()
    existing = row['cnt'] if row else 0
    if existing > 0:
        return {'status': 'skipped', 'existing_snapshots': existing,
                'message': 'Backfill already run. Delete existing daily snapshots to re-run.'}

    # Get date range from cycle_log
    cursor = await conn.execute(
        "SELECT MIN(ts) as first_ts, MAX(ts) as last_ts FROM cycle_log"
    )
    row = await cursor.fetchone()
    if not row or not row['first_ts']:
        return {'status': 'empty', 'message': 'No cycle_log data to backfill from.'}

    first_ts = row['first_ts']
    last_ts = row['last_ts']

    first_dt = _parse_ts(first_ts)
    last_dt = _parse_ts(last_ts)
    if not first_dt or not last_dt:
        return {'status': 'error', 'message': 'Could not parse cycle_log timestamps.'}

    # Iterate day by day
    current = first_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end = last_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    days_processed = 0
    snapshots_written = 0

    while current < end:
        # Use space-formatted timestamps for action_log compatibility
        # (CURRENT_TIMESTAMP writes YYYY-MM-DD HH:MM:SS).
        # Use datetime() SQL function for format-agnostic comparison.
        day_start_str = current.strftime('%Y-%m-%d %H:%M:%S')
        day_end_dt = current + timedelta(days=1)
        day_end_str = day_end_dt.strftime('%Y-%m-%d %H:%M:%S')
        # cycle_log.ts uses ISO-8601 — datetime() handles both formats
        day_end_iso = day_end_dt.isoformat()
        day_str = current.strftime('%Y-%m-%d')

        # M1: Cumulative cycle count up to this day
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM cycle_log WHERE datetime(ts) < datetime(?)",
            (day_end_iso,),
        )
        row = await cursor.fetchone()
        cumulative_cycles = row['cnt'] if row else 0

        if cumulative_cycles > 0:
            await _connection._exec_write(
                """INSERT INTO metrics_snapshots (timestamp, metric_name, value, details, period)
                   VALUES (?, ?, ?, ?, ?)""",
                (day_str + 'T23:59:59+00:00', 'uptime', float(cumulative_cycles),
                 json.dumps({'cycles': cumulative_cycles, 'day': day_str}), 'daily'),
            )
            snapshots_written += 1

        # M2: Initiative rate for this day
        cursor = await conn.execute(
            """SELECT
                 COUNT(*) as total,
                 COUNT(CASE WHEN cl.mode != 'visitor' THEN 1 END) as self_initiated
               FROM action_log al
               JOIN cycle_log cl ON al.cycle_id = cl.id
               WHERE al.status = 'executed'
                 AND datetime(al.created_at) >= datetime(?)
                 AND datetime(al.created_at) < datetime(?)""",
            (day_start_str, day_end_str),
        )
        row = await cursor.fetchone()
        total_actions = row['total'] if row else 0
        self_initiated = row['self_initiated'] if row else 0
        rate = (self_initiated / total_actions * 100.0) if total_actions > 0 else 0.0

        if total_actions > 0:
            await _connection._exec_write(
                """INSERT INTO metrics_snapshots (timestamp, metric_name, value, details, period)
                   VALUES (?, ?, ?, ?, ?)""",
                (day_str + 'T23:59:59+00:00', 'initiative_rate', round(rate, 2),
                 json.dumps({'total': total_actions, 'self': self_initiated, 'day': day_str}),
                 'daily'),
            )
            snapshots_written += 1

        # M7: Cumulative emotional range up to this day
        cursor = await conn.execute(
            "SELECT drives FROM cycle_log WHERE drives IS NOT NULL AND datetime(ts) < datetime(?)",
            (day_end_iso,),
        )
        rows = await cursor.fetchall()
        bins_visited = set()
        for r in rows:
            try:
                drives = json.loads(r['drives']) if isinstance(r['drives'], str) else r['drives']
                if not drives:
                    continue
                v = drives.get('mood_valence', 0.0)
                a = drives.get('mood_arousal', 0.3)
                e = drives.get('energy', 0.8)
                bins_visited.add((_quantize(_normalize_valence(v)), _quantize(a), _quantize(e)))
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        if bins_visited:
            await _connection._exec_write(
                """INSERT INTO metrics_snapshots (timestamp, metric_name, value, details, period)
                   VALUES (?, ?, ?, ?, ?)""",
                (day_str + 'T23:59:59+00:00', 'emotional_range', float(len(bins_visited)),
                 json.dumps({'states': len(bins_visited), 'total_possible': 125, 'day': day_str}),
                 'daily'),
            )
            snapshots_written += 1

        current += timedelta(days=1)
        days_processed += 1

    return {
        'status': 'completed',
        'days_processed': days_processed,
        'snapshots_written': snapshots_written,
        'date_range': f"{first_dt.strftime('%Y-%m-%d')} to {last_dt.strftime('%Y-%m-%d')}",
    }


def _parse_ts(ts_str: str) -> datetime | None:
    """Parse an ISO timestamp from the DB."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
