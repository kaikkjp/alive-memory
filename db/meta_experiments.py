"""db.meta_experiments — Meta-controller experiment log CRUD (TASK-090, TASK-091).

Records parameter adjustments made by the meta-controller during sleep.
TASK-091 adds evaluation, revert, confidence tracking, and side-effect detection.
"""

import json
import clock
import db.connection as _connection


# ── Experiment CRUD (TASK-090) ──

async def record_experiment(
    cycle_at_change: int,
    param_name: str,
    old_value: float,
    new_value: float,
    reason: str,
    target_metric: str,
    metric_value_at_change: float,
    confidence_at_change: float | None = None,
) -> int:
    """Record a meta-controller adjustment. Returns the experiment id."""
    now = clock.now_utc().isoformat()
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """INSERT INTO meta_experiments
           (cycle_at_change, param_name, old_value, new_value, reason,
            target_metric, metric_value_at_change, outcome,
            confidence_at_change, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (cycle_at_change, param_name, old_value, new_value, reason,
         target_metric, metric_value_at_change, confidence_at_change, now),
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
    """Get experiments awaiting evaluation."""
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


# ── Evaluation updates (TASK-091) ──

async def update_experiment_outcome(
    experiment_id: int,
    outcome: str,
    metric_value_after: float,
    evaluation_cycle: int,
    side_effects: list[dict] | None = None,
    reverted_at_cycle: int | None = None,
) -> None:
    """Update a pending experiment with its evaluation result."""
    conn = await _connection.get_db()
    side_effects_json = json.dumps(side_effects) if side_effects else None
    await conn.execute(
        """UPDATE meta_experiments
           SET outcome = ?,
               metric_value_after = ?,
               evaluation_cycle = ?,
               side_effects = ?,
               reverted_at_cycle = ?
           WHERE id = ?""",
        (outcome, metric_value_after, evaluation_cycle,
         side_effects_json, reverted_at_cycle, experiment_id),
    )
    await conn.commit()


async def get_experiment_history(limit: int = 50) -> list[dict]:
    """Get experiments with outcomes for dashboard display."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, cycle_at_change, param_name, old_value, new_value,
                  reason, target_metric, metric_value_at_change,
                  metric_value_after, outcome, evaluation_cycle,
                  side_effects, confidence_at_change, reverted_at_cycle,
                  created_at
           FROM meta_experiments
           ORDER BY cycle_at_change DESC
           LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get('side_effects'):
            try:
                d['side_effects'] = json.loads(d['side_effects'])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(d)
    return results


# ── Confidence CRUD (TASK-091) ──

async def get_confidence(param_name: str, target_metric: str) -> dict | None:
    """Get confidence record for a param->metric link."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM meta_confidence
           WHERE param_name = ? AND target_metric = ?""",
        (param_name, target_metric),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_confidence(
    param_name: str,
    target_metric: str,
    outcome: str,
    effect_size: float,
    cycle: int,
) -> dict:
    """Update confidence for a param->metric link based on an evaluation outcome.

    Creates the record if it doesn't exist. Returns the updated record.
    """
    conn = await _connection.get_db()
    existing = await get_confidence(param_name, target_metric)

    if existing is None:
        attempts = 1
        improved = 1 if outcome == 'improved' else 0
        degraded = 1 if outcome == 'degraded' else 0
        neutral = 1 if outcome == 'neutral' else 0
        confidence = improved / attempts
        await conn.execute(
            """INSERT INTO meta_confidence
               (param_name, target_metric, attempts, improved, degraded, neutral,
                confidence, avg_effect_size, last_updated_cycle)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (param_name, target_metric, attempts, improved, degraded, neutral,
             confidence, abs(effect_size), cycle),
        )
    else:
        attempts = existing['attempts'] + 1
        improved = existing['improved'] + (1 if outcome == 'improved' else 0)
        degraded = existing['degraded'] + (1 if outcome == 'degraded' else 0)
        neutral = existing['neutral'] + (1 if outcome == 'neutral' else 0)
        confidence = improved / attempts if attempts > 0 else 0.5
        old_avg = existing['avg_effect_size'] or 0.0
        avg_effect = (old_avg * (attempts - 1) + abs(effect_size)) / attempts
        await conn.execute(
            """UPDATE meta_confidence
               SET attempts = ?, improved = ?, degraded = ?, neutral = ?,
                   confidence = ?, avg_effect_size = ?, last_updated_cycle = ?
               WHERE param_name = ? AND target_metric = ?""",
            (attempts, improved, degraded, neutral, round(confidence, 4),
             round(avg_effect, 4), cycle, param_name, target_metric),
        )

    await conn.commit()
    return {
        'param_name': param_name,
        'target_metric': target_metric,
        'attempts': attempts,
        'improved': improved,
        'degraded': degraded,
        'neutral': neutral,
        'confidence': round(confidence, 4),
    }


async def get_all_confidence() -> list[dict]:
    """Get all confidence records for dashboard display."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT * FROM meta_confidence
           ORDER BY attempts DESC"""
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
