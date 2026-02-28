"""Dynamic action registry CRUD.

Tracks actions the Shopkeeper attempts that aren't in ACTION_REGISTRY.
Supports alias resolution, body-state actions, and pending/promoted lifecycle.
Pattern follows db/parameters.py.
"""
from __future__ import annotations
import db.connection as _connection
import clock


async def get_dynamic_action(action_name: str) -> dict | None:
    """Get a single dynamic action by name. Returns None if not found."""
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM dynamic_actions WHERE action_name = ?", (action_name,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_all_dynamic_actions() -> list[dict]:
    """Get all dynamic actions ordered by attempt_count desc."""
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM dynamic_actions ORDER BY attempt_count DESC"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_dynamic_actions_by_status(status: str) -> list[dict]:
    """Get dynamic actions filtered by status."""
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM dynamic_actions WHERE status = ? ORDER BY attempt_count DESC",
        (status,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def record_unknown_action(action_name: str) -> dict:
    """Record or increment an unknown action attempt.

    If new: INSERT with status='pending', attempt_count=1.
    If exists: increment attempt_count, update last_seen.
    Returns the current row as dict.
    """
    now = clock.now_utc().isoformat()
    existing = await get_dynamic_action(action_name)

    if existing is None:
        await _connection._exec_write(
            "INSERT INTO dynamic_actions (action_name, status, attempt_count, first_seen, last_seen) "
            "VALUES (?, 'pending', 1, ?, ?)",
            (action_name, now, now)
        )
    else:
        await _connection._exec_write(
            "UPDATE dynamic_actions SET attempt_count = attempt_count + 1, last_seen = ? "
            "WHERE action_name = ?",
            (now, action_name)
        )

    return await get_dynamic_action(action_name)


async def resolve_action(action_name: str, status: str, alias_for: str | None = None,
                         body_state: str | None = None, resolved_by: str = 'operator') -> dict:
    """Resolve a dynamic action to a specific status.

    status: 'alias' | 'body_state' | 'promoted' | 'rejected'
    alias_for: target action name (required when status='alias')
    body_state: JSON string (required when status='body_state')
    """
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        "UPDATE dynamic_actions SET status = ?, alias_for = ?, body_state = ?, "
        "resolved_by = ?, last_seen = ? WHERE action_name = ?",
        (status, alias_for, body_state, resolved_by, now, action_name)
    )
    return await get_dynamic_action(action_name)


async def promote_pending_actions(threshold: int = 5) -> list[dict]:
    """Auto-promote pending actions whose attempt_count >= their own promote_threshold.

    The per-row `promote_threshold` column is used when set; `threshold` is the
    fallback applied to rows where promote_threshold is NULL or <= 0.

    Returns list of promoted actions.
    """
    now = clock.now_utc().isoformat()
    db = await _connection.get_db()

    # Promote rows where attempt_count meets the per-row threshold (falling back
    # to the global `threshold` argument for rows without one).
    cursor = await db.execute(
        "SELECT * FROM dynamic_actions WHERE status = 'pending' "
        "AND attempt_count >= COALESCE(NULLIF(promote_threshold, 0), ?)",
        (threshold,)
    )
    candidates = [dict(r) for r in await cursor.fetchall()]

    for candidate in candidates:
        await _connection._exec_write(
            "UPDATE dynamic_actions SET status = 'promoted', resolved_by = 'auto', last_seen = ? "
            "WHERE action_name = ?",
            (now, candidate['action_name'])
        )

    return [await get_dynamic_action(c['action_name']) for c in candidates]


async def get_action_stats() -> dict:
    """Get summary statistics for the dynamic actions registry."""
    db = await _connection.get_db()

    # Count by status
    cursor = await db.execute(
        "SELECT status, COUNT(*) as count FROM dynamic_actions GROUP BY status"
    )
    rows = await cursor.fetchall()
    by_status = {r['status']: r['count'] for r in rows}

    # Total
    cursor2 = await db.execute("SELECT COUNT(*) as total FROM dynamic_actions")
    total_row = await cursor2.fetchone()
    total = total_row['total'] if total_row else 0

    # Top pending (most attempted)
    cursor3 = await db.execute(
        "SELECT action_name, attempt_count FROM dynamic_actions "
        "WHERE status = 'pending' ORDER BY attempt_count DESC LIMIT 10"
    )
    top_pending = [dict(r) for r in await cursor3.fetchall()]

    return {
        'total': total,
        'by_status': by_status,
        'top_pending': top_pending,
    }
