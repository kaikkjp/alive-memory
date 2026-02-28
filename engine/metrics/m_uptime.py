"""M1: Uptime — Cycles Lived.

Source: cycle_log table.
Calculation: COUNT(*) + first/last cycle timestamps for days alive.
"""

import json
from metrics.models import MetricResult
import db.connection as _connection


async def compute() -> MetricResult:
    """Compute M1 uptime metric."""
    conn = await _connection.get_db()

    # Total cycles
    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM cycle_log")
    row = await cursor.fetchone()
    total_cycles = row['cnt'] if row else 0

    # First and last cycle timestamps for days alive
    cursor = await conn.execute(
        "SELECT MIN(ts) as first_ts, MAX(ts) as last_ts FROM cycle_log"
    )
    row = await cursor.fetchone()
    first_ts = row['first_ts'] if row else None
    last_ts = row['last_ts'] if row else None

    days_alive = 0
    if first_ts and last_ts:
        from datetime import datetime, timezone
        try:
            first_dt = datetime.fromisoformat(first_ts.replace('Z', '+00:00'))
            last_dt = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))
            if first_dt.tzinfo is None:
                first_dt = first_dt.replace(tzinfo=timezone.utc)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            days_alive = max(1, (last_dt - first_dt).days + 1)
        except (ValueError, TypeError):
            days_alive = 1 if total_cycles > 0 else 0

    display = f"Alive for {days_alive} day{'s' if days_alive != 1 else ''} ({total_cycles:,} cycles)"

    return MetricResult(
        name='uptime',
        value=float(total_cycles),
        details={
            'cycles': total_cycles,
            'days_alive': days_alive,
            'first_cycle': first_ts,
            'last_cycle': last_ts,
        },
        display=display,
    )
