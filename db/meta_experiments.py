"""db.meta_experiments — Meta-controller experiment log CRUD (TASK-090).

Records parameter adjustments made by the meta-controller during sleep.
TASK-091 will add evaluation and revert logic.
"""

import clock
import db.connection as _connection


async def record_experiment(
    cycle_at_change: int,
    param_name: str,
    old_value: float,
    new_value: float,
    reason: str,
    target_metric: str,
    metric_value_at_change: float,
) -> int:
    """Record a meta-controller adjustment. Returns the experiment id."""
    now = clock.now_utc().isoformat()
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """INSERT INTO meta_experiments
           (cycle_at_change, param_name, old_value, new_value, reason,
            target_metric, metric_value_at_change, outcome, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (cycle_at_change, param_name, old_value, new_value, reason,
         target_metric, metric_value_at_change, now),
    )
    await conn.commit()
    return cursor.lastrowid


async def get_recent_experiments(limit: int = 20) -> list[dict]:
    """Get recent experiments, most recent first."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM meta_experiments
           ORDER BY cycle_at_change DESC
           LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_pending_experiments() -> list[dict]:
    """Get experiments awaiting evaluation (TASK-091)."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM meta_experiments
           WHERE outcome = 'pending'
           ORDER BY cycle_at_change ASC"""
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_last_adjustment_cycle(param_name: str) -> int | None:
    """Get the cycle number of the last adjustment for a parameter.

    Returns None if the parameter has never been adjusted.
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT cycle_at_change FROM meta_experiments
           WHERE param_name = ?
           ORDER BY cycle_at_change DESC
           LIMIT 1""",
        (param_name,),
    )
    row = await cursor.fetchone()
    return row['cycle_at_change'] if row else None


async def get_latest_metric_value(metric_name: str) -> dict | None:
    """Get the latest metric snapshot for a metric name.

    Returns dict with 'value' and 'timestamp', or None if no snapshot exists.
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT value, timestamp FROM metrics_snapshots
           WHERE metric_name = ?
           ORDER BY timestamp DESC LIMIT 1""",
        (metric_name,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None
