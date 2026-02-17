"""db.analytics — Cycle logs, LLM cost tracking, action log, inhibitions,
habits, and dashboard queries."""

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import clock
import db.connection as _connection
from db.connection import JST


# ─── Cycle Log ───

async def log_cycle(log: dict):
    await _connection._exec_write(
        """INSERT INTO cycle_log
           (id, mode, drives, focus_salience, focus_type, routing_focus,
            token_budget, memory_count, internal_monologue, dialogue,
            expression, body_state, gaze, actions, dropped,
            next_cycle_hints, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (log['id'], log['mode'], json.dumps(log.get('drives', {})),
         log.get('focus_salience'), log.get('focus_type'),
         log.get('routing_focus'), log.get('token_budget'),
         log.get('memory_count'), log.get('internal_monologue'),
         log.get('dialogue'), log.get('expression'),
         log.get('body_state', 'sitting'), log.get('gaze', 'at_visitor'),
         json.dumps(log.get('actions', [])), json.dumps(log.get('dropped', [])),
         json.dumps(log.get('next_cycle_hints', [])),
         clock.now_utc().isoformat())
    )


async def get_last_cycle_log() -> dict | None:
    """Fetch the most recent cycle_log entry for self_state assembly."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT body_state, gaze, expression, internal_monologue,
                  actions, next_cycle_hints, dialogue, mode
           FROM cycle_log ORDER BY ts DESC LIMIT 1"""
    )
    row = await cursor.fetchone()
    if not row:
        return None
    raw_hints = json.loads(row['next_cycle_hints']) if row['next_cycle_hints'] else []
    return {
        'body_state': row['body_state'] or 'sitting',
        'gaze': row['gaze'] or 'at_visitor',
        'expression': row['expression'] or 'neutral',
        'internal_monologue': row['internal_monologue'] or '',
        'actions': json.loads(row['actions']) if row['actions'] else [],
        'next_cycle_hints': raw_hints if isinstance(raw_hints, list) else [],
        'dialogue': row['dialogue'],
        'mode': row['mode'],
    }


async def get_last_creative_cycle() -> Optional[dict]:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM cycle_log WHERE mode IN ('express', 'autonomous') ORDER BY ts DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return {
        'mode': row['mode'],
        'ts': row['ts'],
        'dialogue': row['dialogue'],
        'internal_monologue': row['internal_monologue'],
    }


# ─── Count Utilities ───

async def count_journal_entries() -> int:
    """Count total journal entries."""
    conn = await _connection.get_db()
    cursor = await conn.execute("SELECT COUNT(*) FROM journal_entries")
    row = await cursor.fetchone()
    return row[0] if row else 0


async def count_cycle_logs() -> int:
    """Count total cycle log entries."""
    conn = await _connection.get_db()
    cursor = await conn.execute("SELECT COUNT(*) FROM cycle_log")
    row = await cursor.fetchone()
    return row[0] if row else 0


# ─── LLM Call Log ───

async def insert_llm_call_log(
    call_id: str,
    provider: str,
    model: str,
    purpose: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    cycle_id: str = None,
):
    """Insert LLM call log entry for cost tracking."""
    now = datetime.now(timezone.utc).isoformat()
    await _connection._exec_write(
        """INSERT INTO llm_call_log
           (id, provider, model, purpose, input_tokens, output_tokens, cost_usd, cycle_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (call_id, provider, model, purpose, input_tokens, output_tokens, cost_usd, cycle_id, now)
    )


async def get_llm_call_cost_today() -> float:
    """Get total LLM cost for today (JST)."""
    conn = await _connection.get_db()
    today_jst = datetime.now(JST).date().isoformat()
    cursor = await conn.execute(
        "SELECT SUM(cost_usd) as total FROM llm_call_log WHERE date(created_at, '+9 hours') = ?",
        (today_jst,)
    )
    row = await cursor.fetchone()
    return row['total'] if row and row['total'] else 0.0


async def get_llm_call_count_today() -> int:
    """Get total LLM call count for today (JST)."""
    conn = await _connection.get_db()
    today_jst = datetime.now(JST).date().isoformat()
    cursor = await conn.execute(
        "SELECT COUNT(*) as cnt FROM llm_call_log WHERE date(created_at, '+9 hours') = ?",
        (today_jst,)
    )
    row = await cursor.fetchone()
    return row['cnt'] if row else 0


async def get_llm_costs_summary(days: int = 30) -> dict:
    """Get LLM cost summary for dashboard.

    Returns:
        {
            'today': float,
            '7d_avg': float,
            '30d_total': float,
            'breakdown': [{'purpose': str, 'cost': float, 'calls': int}],
        }
    """
    conn = await _connection.get_db()
    today_jst = datetime.now(JST).date().isoformat()

    # Today's total
    cursor = await conn.execute(
        "SELECT SUM(cost_usd) as total FROM llm_call_log WHERE date(created_at, '+9 hours') = ?",
        (today_jst,)
    )
    row = await cursor.fetchone()
    today_cost = row['total'] if row and row['total'] else 0.0

    # 7-day average (total cost / 7 days, including zero-cost days)
    cursor = await conn.execute(
        """SELECT SUM(cost_usd) as total FROM llm_call_log
           WHERE created_at >= datetime('now', '-7 days')"""
    )
    row = await cursor.fetchone()
    total_7d = row['total'] if row and row['total'] else 0.0
    avg_7d = total_7d / 7.0

    # 30-day total
    cursor = await conn.execute(
        """SELECT SUM(cost_usd) as total FROM llm_call_log
           WHERE created_at >= datetime('now', '-30 days')"""
    )
    row = await cursor.fetchone()
    total_30d = row['total'] if row and row['total'] else 0.0

    # Breakdown by purpose (today)
    cursor = await conn.execute(
        """SELECT purpose, SUM(cost_usd) as cost, COUNT(*) as calls
           FROM llm_call_log
           WHERE date(created_at, '+9 hours') = ?
           GROUP BY purpose
           ORDER BY cost DESC""",
        (today_jst,)
    )
    rows = await cursor.fetchall()
    breakdown = [{'purpose': r['purpose'], 'cost': r['cost'], 'calls': r['calls']} for r in rows]

    return {
        'today': today_cost,
        '7d_avg': avg_7d,
        '30d_total': total_30d,
        'breakdown': breakdown,
    }


async def get_llm_daily_costs(days: int = 30) -> list[dict]:
    """Get daily cost array for dashboard sparkline chart.

    Returns:
        [{'date': 'YYYY-MM-DD', 'cost': float}, ...]
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT date(created_at, '+9 hours') as day, SUM(cost_usd) as cost
           FROM llm_call_log
           WHERE created_at >= datetime('now', '-' || ? || ' days')
           GROUP BY day
           ORDER BY day ASC""",
        (days,)
    )
    rows = await cursor.fetchall()
    return [{'date': r['day'], 'cost': r['cost']} for r in rows]


# ── Action Log (Phase 2) ──

async def log_action(cycle_id: str, action: str, status: str,
                     source: str = 'cortex', impulse: float = None,
                     priority: float = None, content: str = None,
                     target: str = None, suppression_reason: str = None,
                     energy_cost: float = None, success: bool = None,
                     error: str = None) -> None:
    """Log an action decision or execution result to action_log."""
    action_id = str(uuid.uuid4())[:12]
    await _connection._exec_write(
        """INSERT INTO action_log
           (id, cycle_id, action, status, source, impulse, priority,
            content, target, suppression_reason, energy_cost, success, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (action_id, cycle_id, action, status, source, impulse, priority,
         content, target, suppression_reason, energy_cost, success, error),
    )


async def get_recent_suppressions(limit: int = 10,
                                  min_impulse: float = 0.3) -> list[dict]:
    """Get recently suppressed actions above impulse threshold."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT action, impulse, suppression_reason, content, target,
                  created_at
           FROM action_log
           WHERE status IN ('suppressed', 'incapable', 'deferred')
           AND impulse >= ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (min_impulse, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_action_log(limit: int = 50, status_filter: str = None,
                         action_filter: str = None) -> list[dict]:
    """Get recent action log entries with optional filters."""
    conn = await _connection.get_db()
    conditions = []
    params = []
    if status_filter:
        conditions.append("status = ?")
        params.append(status_filter)
    if action_filter:
        conditions.append("action = ?")
        params.append(action_filter)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    cursor = await conn.execute(
        f"""SELECT id, cycle_id, action, status, source, impulse, priority,
                   content, target, suppression_reason, energy_cost,
                   success, error, created_at
            FROM action_log
            {where}
            ORDER BY created_at DESC
            LIMIT ?""",
        tuple(params),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ── Inhibitions (Phase 3) ──

async def create_inhibition(action: str, pattern: str, reason: str,
                            strength: float = 0.3) -> str:
    """Create a new learned inhibition. Returns the inhibition id."""
    inhibition_id = str(uuid.uuid4())[:12]
    await _connection._exec_write(
        """INSERT INTO inhibitions
           (id, action, pattern, reason, strength)
           VALUES (?, ?, ?, ?, ?)""",
        (inhibition_id, action, pattern, reason, strength),
    )
    return inhibition_id


async def get_inhibitions_for_action(action: str) -> list[dict]:
    """Get inhibitions for a specific action, strength >= 0.2."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, action, pattern, reason, strength,
                  formed_at, last_triggered, trigger_count
           FROM inhibitions
           WHERE action = ? AND strength >= 0.2
           ORDER BY strength DESC""",
        (action,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_inhibition(inhibition_id: str, **kwargs) -> None:
    """Update inhibition fields (strength, last_triggered, trigger_count)."""
    if not kwargs:
        return
    allowed = {'strength', 'last_triggered', 'trigger_count'}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return
    vals.append(inhibition_id)
    await _connection._exec_write(
        f"UPDATE inhibitions SET {', '.join(sets)} WHERE id = ?",
        tuple(vals),
    )


async def delete_inhibition(inhibition_id: str) -> None:
    """Delete an inhibition (when strength drops below 0.05)."""
    await _connection._exec_write("DELETE FROM inhibitions WHERE id = ?", (inhibition_id,))


async def find_matching_inhibition(action: str, pattern_json: str) -> dict | None:
    """Find an existing inhibition matching action and pattern."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, action, pattern, reason, strength,
                  formed_at, last_triggered, trigger_count
           FROM inhibitions
           WHERE action = ? AND pattern = ?
           LIMIT 1""",
        (action, pattern_json),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_recent_inhibitions(limit: int = 5,
                                 min_strength: float = 0.2) -> list[dict]:
    """Get recent inhibitions for cortex context injection."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT action, strength, trigger_count, reason, formed_at
           FROM inhibitions
           WHERE strength >= ?
           ORDER BY strength DESC, trigger_count DESC
           LIMIT ?""",
        (min_strength, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_all_inhibitions() -> list[dict]:
    """Get all inhibitions for peek command."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, action, pattern, reason, strength,
                  formed_at, last_triggered, trigger_count
           FROM inhibitions
           ORDER BY strength DESC""",
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ── Habits (Phase 4, TASK-011a) ──

async def create_habit(action: str, trigger_context: str,
                       strength: float = 0.1) -> str:
    """Create a new habit entry. Returns the habit id."""
    habit_id = str(uuid.uuid4())[:12]
    now = clock.now_utc()
    await _connection._exec_write(
        """INSERT INTO habits
           (id, action, trigger_context, strength, repetition_count,
            formed_at, last_triggered)
           VALUES (?, ?, ?, ?, 1, ?, ?)""",
        (habit_id, action, trigger_context, strength, now, now),
    )
    return habit_id


async def get_habits_for_action(action: str) -> list[dict]:
    """Get all habits for a specific action type."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, action, trigger_context, strength,
                  repetition_count, formed_at, last_triggered
           FROM habits
           WHERE action = ?
           ORDER BY strength DESC""",
        (action,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def find_matching_habit(action: str, trigger_context: str) -> dict | None:
    """Find an existing habit matching action and trigger context."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, action, trigger_context, strength,
                  repetition_count, formed_at, last_triggered
           FROM habits
           WHERE action = ? AND trigger_context = ?
           LIMIT 1""",
        (action, trigger_context),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_habit(habit_id: str, **kwargs) -> None:
    """Update habit fields (strength, repetition_count, last_triggered)."""
    if not kwargs:
        return
    allowed = {'strength', 'repetition_count', 'last_triggered'}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return
    vals.append(habit_id)
    await _connection._exec_write(
        f"UPDATE habits SET {', '.join(sets)} WHERE id = ?",
        tuple(vals),
    )


async def delete_habit(habit_id: str) -> None:
    """Delete a habit."""
    await _connection._exec_write("DELETE FROM habits WHERE id = ?", (habit_id,))


async def get_all_habits() -> list[dict]:
    """Get all habits for peek/debug commands."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, action, trigger_context, strength,
                  repetition_count, formed_at, last_triggered
           FROM habits
           ORDER BY strength DESC""",
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ── Dashboard queries (TASK-015) ──

async def get_actions_today() -> list[dict]:
    """Get action counts and energy totals for today (JST), grouped by action type."""
    conn = await _connection.get_db()
    jst_now = clock.now()  # already JST
    day_start = jst_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    # Convert to UTC strings for DB comparison (CURRENT_TIMESTAMP stores UTC)
    day_start_utc = day_start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    day_end_utc = day_end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    cursor = await conn.execute(
        """SELECT action AS type, COUNT(*) AS count,
                  COALESCE(SUM(energy_cost), 0) AS total_energy
           FROM action_log
           WHERE status = 'executed'
             AND created_at >= ? AND created_at < ?
           GROUP BY action
           ORDER BY count DESC""",
        (day_start_utc, day_end_utc),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_action_capabilities() -> list[dict]:
    """Get action capabilities with cooldown status from registry + action_log."""
    from pipeline.action_registry import ACTION_REGISTRY
    conn = await _connection.get_db()
    # Get most recent executed timestamp per action for cooldown check
    cursor = await conn.execute(
        """SELECT action, MAX(created_at) AS last_used
           FROM action_log
           WHERE status = 'executed'
           GROUP BY action"""
    )
    last_used_rows = await cursor.fetchall()
    last_used_map = {r['action']: r['last_used'] for r in last_used_rows}

    now = clock.now_utc()
    capabilities = []
    for name, cap in ACTION_REGISTRY.items():
        last = last_used_map.get(name)
        cooling_until = None
        ready = True
        if cap.cooldown_seconds > 0 and last:
            from datetime import datetime, timedelta
            try:
                last_dt = datetime.fromisoformat(last)
                # CURRENT_TIMESTAMP stores UTC without tzinfo — make aware
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                cooldown_end = last_dt + timedelta(seconds=cap.cooldown_seconds)
                if now < cooldown_end:
                    ready = False
                    cooling_until = cooldown_end.isoformat()
            except (ValueError, TypeError):
                pass
        if not cap.enabled:
            ready = False
        capabilities.append({
            'action': name,
            'enabled': cap.enabled,
            'ready': ready,
            'cooling_until': cooling_until,
            'energy_cost': 0.0,
        })
    return capabilities


async def get_top_habits(limit: int = 5) -> list[dict]:
    """Get top habits ordered by strength descending."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, action, trigger_context, strength,
                  repetition_count AS fire_count, formed_at,
                  last_triggered AS last_fired
           FROM habits
           ORDER BY strength DESC
           LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_active_inhibitions() -> list[dict]:
    """Get active inhibitions (strength > 0.05) for dashboard display."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, action, pattern AS context, strength,
                  trigger_count, formed_at
           FROM inhibitions
           WHERE strength > 0.05
           ORDER BY strength DESC"""
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_recent_suppressions_dashboard(limit: int = 10,
                                            min_impulse: float = 0.5) -> list[dict]:
    """Get recently suppressed actions for dashboard 'she almost...' feed."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT action, impulse, suppression_reason AS reason,
                  created_at AS timestamp
           FROM action_log
           WHERE status = 'suppressed' AND impulse >= ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (min_impulse, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_habit_skip_count_today() -> int:
    """Count cycles today (JST) where a habit auto-fired (cortex skipped)."""
    conn = await _connection.get_db()
    jst_now = clock.now()
    day_start = jst_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    day_start_utc = day_start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    day_end_utc = day_end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    cursor = await conn.execute(
        """SELECT COUNT(*) AS cnt FROM action_log
           WHERE source = 'habit'
             AND created_at >= ? AND created_at < ?""",
        (day_start_utc, day_end_utc),
    )
    row = await cursor.fetchone()
    return row['cnt'] if row else 0


async def get_budget_remaining() -> dict:
    """Get real-dollar budget remaining since last sleep reset.

    TASK-050: Energy = money. Every API call that costs real dollars is tracked
    in llm_call_log. Remaining budget is a derived value:
        remaining = daily_budget - SUM(cost_usd WHERE created_at >= last_sleep_reset)

    Returns:
        {'budget': float, 'spent': float, 'remaining': float}
    """
    from db.state import get_setting

    conn = await _connection.get_db()

    # Get daily budget from settings (default $5.00)
    budget_str = await get_setting('daily_budget')
    budget = float(budget_str) if budget_str else 5.0

    # Get last sleep reset timestamp (default: today midnight JST in UTC)
    last_reset_str = await get_setting('last_sleep_reset')
    if last_reset_str:
        last_reset = last_reset_str
    else:
        # Fall back to today midnight JST → UTC
        jst_now = clock.now()
        midnight_jst = jst_now.replace(hour=0, minute=0, second=0, microsecond=0)
        last_reset = midnight_jst.astimezone(timezone.utc).isoformat()

    # Sum all API costs since last reset
    cursor = await conn.execute(
        """SELECT COALESCE(SUM(cost_usd), 0) AS spent
           FROM llm_call_log
           WHERE created_at >= ?""",
        (last_reset,),
    )
    row = await cursor.fetchone()
    spent = round(row['spent'], 6) if row else 0.0

    remaining = round(budget - spent, 6)
    return {'budget': budget, 'spent': spent, 'remaining': remaining}


async def get_executed_action_count_today() -> int:
    """Count total executed actions today (JST) for mood bonus scaling."""
    conn = await _connection.get_db()
    jst_now = clock.now()
    day_start = jst_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    day_start_utc = day_start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    day_end_utc = day_end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    cursor = await conn.execute(
        """SELECT COUNT(*) AS cnt FROM action_log
           WHERE status = 'executed'
             AND created_at >= ? AND created_at < ?""",
        (day_start_utc, day_end_utc),
    )
    row = await cursor.fetchone()
    return row['cnt'] if row else 0
