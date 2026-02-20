"""M2: Autonomous Initiative Rate.

Source: action_log + cycle_log tables.
Calculation: % of executed actions in cycles with no visitor_message event.

Classification:
  - 'self': action in a cycle with no visitor present
  - 'visitor': action in a cycle with a visitor present
We infer from the cycle_log mode column: 'visitor' mode = visitor-triggered,
everything else = self-initiated.
"""

from datetime import timedelta
from metrics.models import MetricResult
import clock
import db.connection as _connection


async def compute(hours: int = 24) -> MetricResult:
    """Compute M2 initiative rate over the given time window."""
    conn = await _connection.get_db()
    # Use strftime to produce space-formatted timestamp matching CURRENT_TIMESTAMP
    # format used by action_log.created_at (YYYY-MM-DD HH:MM:SS).
    cutoff = (clock.now_utc() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

    # Join action_log with cycle_log to get mode per action.
    # Modes: 'visitor', 'ambient', 'silence', 'express', 'autonomous', 'reactive'
    # Self-initiated = NOT visitor mode
    cursor = await conn.execute(
        """SELECT
             COUNT(*) as total,
             COUNT(CASE WHEN cl.mode != 'visitor' THEN 1 END) as self_initiated,
             COUNT(CASE WHEN cl.mode = 'visitor' THEN 1 END) as visitor_triggered
           FROM action_log al
           JOIN cycle_log cl ON al.cycle_id = cl.id
           WHERE al.status = 'executed'
             AND datetime(al.created_at) >= datetime(?)""",
        (cutoff,),
    )
    row = await cursor.fetchone()
    total = row['total'] if row else 0
    self_initiated = row['self_initiated'] if row else 0
    visitor_triggered = row['visitor_triggered'] if row else 0

    rate = (self_initiated / total * 100.0) if total > 0 else 0.0

    # Also compute lifetime rate
    cursor = await conn.execute(
        """SELECT
             COUNT(*) as total,
             COUNT(CASE WHEN cl.mode != 'visitor' THEN 1 END) as self_initiated
           FROM action_log al
           JOIN cycle_log cl ON al.cycle_id = cl.id
           WHERE al.status = 'executed'"""
    )
    row = await cursor.fetchone()
    lifetime_total = row['total'] if row else 0
    lifetime_self = row['self_initiated'] if row else 0
    lifetime_rate = (lifetime_self / lifetime_total * 100.0) if lifetime_total > 0 else 0.0

    display = f"{rate:.1f}% self-initiated (last {hours}h)"

    return MetricResult(
        name='initiative_rate',
        value=round(rate, 2),
        details={
            'window_hours': hours,
            'total_actions': total,
            'self_initiated': self_initiated,
            'visitor_triggered': visitor_triggered,
            'rate_pct': round(rate, 2),
            'lifetime_rate_pct': round(lifetime_rate, 2),
            'lifetime_total': lifetime_total,
        },
        display=display,
    )
