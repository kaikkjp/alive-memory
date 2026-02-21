"""Rate limiter for external body actions.

Sliding-window rate limiting with per-hour and per-day caps, plus
per-action cooldown.  Backed by the external_action_log DB table for
persistence across restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import clock
import db.connection as _connection
from runtime_context import resolve_cycle_id, resolve_run_id, resolve_trace_id


@dataclass
class RateLimit:
    per_hour: int
    per_day: int
    cooldown_seconds: int
    energy_cost: float


RATE_LIMITS: dict[str, RateLimit] = {
    'browse_web':    RateLimit(per_hour=20,  per_day=100, cooldown_seconds=180, energy_cost=0.15),
    'post_x':        RateLimit(per_hour=12,  per_day=50,  cooldown_seconds=300, energy_cost=0.10),
    'reply_x':       RateLimit(per_hour=30,  per_day=100, cooldown_seconds=120, energy_cost=0.08),
    'post_x_image':  RateLimit(per_hour=6,   per_day=20,  cooldown_seconds=600, energy_cost=0.20),
    'tg_send':       RateLimit(per_hour=60,  per_day=500, cooldown_seconds=5,   energy_cost=0.02),
    'tg_send_image': RateLimit(per_hour=20,  per_day=100, cooldown_seconds=30,  energy_cost=0.05),
}


async def check_rate_limit(action_name: str) -> tuple[bool, str]:
    """Check whether *action_name* is allowed right now.

    Returns ``(True, '')`` if allowed, or ``(False, reason)`` if blocked.
    """
    decision = await get_limiter_decision(action_name)
    return bool(decision['allowed']), str(decision.get('reason') or '')


async def get_limiter_decision(action_name: str) -> dict:
    """Return detailed limiter decision for action evidence logging."""
    limit = RATE_LIMITS.get(action_name)
    if not limit:
        return {
            'allowed': True,
            'reason': '',
            'cooldown_state': 'not_limited',
            'rate_limit_remaining': None,
            'limiter_decision': 'allow:no_limit',
        }  # no rate limit configured → allow

    now = clock.now_utc()

    # ── Cooldown check ──
    last_ts = await _get_last_action_timestamp(action_name)
    if last_ts:
        elapsed = (now - last_ts).total_seconds()
        if elapsed < limit.cooldown_seconds:
            remaining = int(limit.cooldown_seconds - elapsed)
            return {
                'allowed': False,
                'reason': f'cooldown: {remaining}s remaining',
                'cooldown_state': f'cooldown:{remaining}s',
                'rate_limit_remaining': 0,
                'limiter_decision': 'deny:cooldown',
            }

    # ── Hourly window ──
    hour_ago = now - timedelta(hours=1)
    hourly_count = await _count_actions_since(action_name, hour_ago)
    remaining_hour = max(limit.per_hour - hourly_count, 0)
    if hourly_count >= limit.per_hour:
        return {
            'allowed': False,
            'reason': f'hourly limit reached ({limit.per_hour}/hr)',
            'cooldown_state': 'ready',
            'rate_limit_remaining': 0,
            'limiter_decision': 'deny:hourly_limit',
        }

    # ── Daily window ──
    day_ago = now - timedelta(hours=24)
    daily_count = await _count_actions_since(action_name, day_ago)
    remaining_day = max(limit.per_day - daily_count, 0)
    if daily_count >= limit.per_day:
        return {
            'allowed': False,
            'reason': f'daily limit reached ({limit.per_day}/day)',
            'cooldown_state': 'ready',
            'rate_limit_remaining': 0,
            'limiter_decision': 'deny:daily_limit',
        }

    return {
        'allowed': True,
        'reason': '',
        'cooldown_state': 'ready',
        'rate_limit_remaining': min(remaining_hour, remaining_day),
        'limiter_decision': 'allow',
    }


async def record_action(action_name: str, success: bool = True,
                        cost_usd: float = 0.0, channel: str = None,
                        error: str = None, payload: str = None,
                        cycle_id: str = None, run_id: str = None,
                        trace_id: str = None,
                        limiter_decision: str = None,
                        cooldown_state: str = None,
                        rate_limit_remaining: int = None) -> None:
    """Record that an external action was executed."""
    now = clock.now_utc()
    resolved_cycle_id = resolve_cycle_id(cycle_id)
    resolved_run_id = resolve_run_id(run_id)
    resolved_trace_id = resolve_trace_id(trace_id)
    await _connection._exec_write(
        """INSERT INTO external_action_log
           (action_name, timestamp, success, cost_usd, channel, error, payload,
            cycle_id, run_id, trace_id, limiter_decision, cooldown_state, rate_limit_remaining)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (action_name, now.isoformat(), int(success), cost_usd,
         channel, error, payload, resolved_cycle_id, resolved_run_id,
         resolved_trace_id, limiter_decision, cooldown_state, rate_limit_remaining),
    )


async def get_rate_limit_status(action_name: str) -> dict:
    """Return current rate limit status for dashboard display."""
    limit = RATE_LIMITS.get(action_name)
    if not limit:
        return {'action': action_name, 'limited': False}

    now = clock.now_utc()
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)

    hourly_count = await _count_actions_since(action_name, hour_ago)
    daily_count = await _count_actions_since(action_name, day_ago)
    last_ts = await _get_last_action_timestamp(action_name)

    cooldown_remaining = 0
    if last_ts:
        elapsed = (now - last_ts).total_seconds()
        if elapsed < limit.cooldown_seconds:
            cooldown_remaining = int(limit.cooldown_seconds - elapsed)

    return {
        'action': action_name,
        'hourly_used': hourly_count,
        'hourly_limit': limit.per_hour,
        'daily_used': daily_count,
        'daily_limit': limit.per_day,
        'cooldown_remaining': cooldown_remaining,
        'cooldown_seconds': limit.cooldown_seconds,
        'energy_cost': limit.energy_cost,
    }


async def is_channel_enabled(channel_name: str) -> bool:
    """Check if a channel is enabled (kill switch check)."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT enabled FROM channel_config WHERE channel_name = ?",
        (channel_name,),
    )
    row = await cursor.fetchone()
    if row is None:
        return False  # unknown channel → disabled
    return bool(row[0])


async def set_channel_enabled(channel_name: str, enabled: bool,
                              changed_by: str = 'operator') -> None:
    """Enable or disable a channel (kill switch)."""
    now = clock.now_utc()
    disabled_at = None if enabled else now.isoformat()
    await _connection._exec_write(
        """INSERT INTO channel_config (channel_name, enabled, disabled_at, disabled_by)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(channel_name) DO UPDATE SET
             enabled = excluded.enabled,
             disabled_at = excluded.disabled_at,
             disabled_by = excluded.disabled_by""",
        (channel_name, int(enabled), disabled_at, changed_by),
    )


async def get_all_channel_status() -> list[dict]:
    """Get status of all channels for dashboard."""
    conn = await _connection.get_db()
    cursor = await conn.execute("SELECT * FROM channel_config")
    rows = await cursor.fetchall()
    return [
        {
            'channel': row[0],
            'enabled': bool(row[1]),
            'disabled_at': row[2],
            'disabled_by': row[3],
        }
        for row in rows
    ]


# ── DB helpers ──

async def _get_last_action_timestamp(action_name: str) -> datetime | None:
    """Get the timestamp of the most recent action of this type."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT timestamp FROM external_action_log
           WHERE action_name = ? ORDER BY timestamp DESC LIMIT 1""",
        (action_name,),
    )
    row = await cursor.fetchone()
    if row and row[0]:
        return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
    return None


async def _count_actions_since(action_name: str, since: datetime) -> int:
    """Count successful actions of this type since a given timestamp."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT COUNT(*) FROM external_action_log
           WHERE action_name = ? AND success = 1 AND timestamp >= ?""",
        (action_name, since.isoformat()),
    )
    row = await cursor.fetchone()
    return row[0] if row else 0
