"""db.social — X/Twitter draft CRUD and social channel management (TASK-057)."""

import hashlib
import re
import uuid
from datetime import timezone, timedelta

import clock
import db.connection as _connection


# ── Write helper (returns rowcount) ──

async def _exec_write_returning_rowcount(sql: str, params: tuple = ()) -> int:
    """Like _exec_write but returns cursor.rowcount for conditional-UPDATE checks.

    Mirrors the lock/commit semantics of connection._exec_write exactly.
    Needed because _exec_write returns None and connection.py is out of scope.
    """
    conn = await _connection.get_db()
    if _connection._tx_depth.get() > 0:
        cursor = await conn.execute(sql, params)
        return cursor.rowcount
    else:
        async with _connection._write_lock:
            cursor = await conn.execute(sql, params)
            await conn.commit()
            return cursor.rowcount


# ── Fingerprinting ──

def _text_fingerprint(text: str) -> str:
    """Normalize text to lowercase, strip punctuation/whitespace, SHA-256 hash.

    Used for dedup — detects similar drafts even with minor formatting differences.
    """
    normalized = re.sub(r'[^\w\s]', '', text.lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:32]


# ── CRUD ──

async def insert_x_draft(draft_text: str, cycle_id: str = None) -> dict:
    """Insert a new X draft with 'pending' status. Returns the created draft dict."""
    draft_id = str(uuid.uuid4())
    fingerprint = _text_fingerprint(draft_text)
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        """INSERT INTO x_drafts (id, draft_text, status, fingerprint, created_at, cycle_id)
           VALUES (?, ?, 'pending', ?, ?, ?)""",
        (draft_id, draft_text, fingerprint, now, cycle_id),
    )
    return {
        'id': draft_id,
        'draft_text': draft_text,
        'status': 'pending',
        'fingerprint': fingerprint,
        'created_at': now,
        'cycle_id': cycle_id,
    }


async def get_pending_drafts(limit: int = 20) -> list[dict]:
    """Get all pending (un-reviewed) drafts, newest first."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, draft_text, status, created_at, cycle_id
           FROM x_drafts WHERE status = 'pending'
           ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_all_drafts(limit: int = 50) -> list[dict]:
    """Get all drafts (all statuses), newest first. For dashboard display."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT id, draft_text, status, created_at, reviewed_at,
                  posted_at, x_post_id, rejection_reason, error_message
           FROM x_drafts ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_pending_count() -> int:
    """Count ALL pending drafts (not limited by display query). Used for dashboard badge."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM x_drafts WHERE status = 'pending'",
    )
    row = await cursor.fetchone()
    return row[0]


async def get_draft_by_id(draft_id: str) -> dict | None:
    """Fetch a single draft by ID."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM x_drafts WHERE id = ?", (draft_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def approve_draft(draft_id: str) -> bool:
    """Mark a draft as approved. Returns True only if exactly one row transitioned.

    Uses rowcount from the conditional UPDATE — immune to clock collisions.
    """
    now = clock.now_utc().isoformat()
    rows = await _exec_write_returning_rowcount(
        "UPDATE x_drafts SET status = 'approved', reviewed_at = ? WHERE id = ? AND status = 'pending'",
        (now, draft_id),
    )
    return rows > 0


async def reject_draft(draft_id: str, reason: str = '') -> bool:
    """Mark a draft as rejected. Returns True only if exactly one row transitioned.

    Uses rowcount from the conditional UPDATE — immune to clock collisions.
    """
    now = clock.now_utc().isoformat()
    rows = await _exec_write_returning_rowcount(
        "UPDATE x_drafts SET status = 'rejected', reviewed_at = ?, rejection_reason = ? WHERE id = ? AND status = 'pending'",
        (now, reason, draft_id),
    )
    return rows > 0


async def mark_posted(draft_id: str, x_post_id: str) -> None:
    """Mark an approved draft as successfully posted to X."""
    now = clock.now_utc().isoformat()
    await _connection._exec_write(
        "UPDATE x_drafts SET status = 'posted', posted_at = ?, x_post_id = ? WHERE id = ?",
        (now, x_post_id, draft_id),
    )


async def mark_post_failed(draft_id: str, error: str) -> None:
    """Mark an approved draft as failed to post."""
    await _connection._exec_write(
        "UPDATE x_drafts SET status = 'failed', error_message = ? WHERE id = ?",
        (error, draft_id),
    )


# ── Constraint checks ──

async def check_dedup(draft_text: str, window_hours: int = 24) -> bool:
    """Check if a similar draft exists within the time window.

    Returns True if duplicate found (should NOT create draft).
    """
    fingerprint = _text_fingerprint(draft_text)
    cutoff = (clock.now_utc() - timedelta(hours=window_hours)).isoformat()
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT COUNT(*) FROM x_drafts
           WHERE fingerprint = ? AND created_at > ? AND status != 'rejected'""",
        (fingerprint, cutoff),
    )
    row = await cursor.fetchone()
    return row[0] > 0


async def get_daily_post_count() -> int:
    """Count drafts created today (JST day boundary). Excludes rejected."""
    now_jst = clock.now_utc().astimezone(_connection.JST)
    today_start = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start.astimezone(timezone.utc).isoformat()
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM x_drafts WHERE created_at >= ? AND status != 'rejected'",
        (today_start_utc,),
    )
    row = await cursor.fetchone()
    return row[0]


async def check_cooldown(cooldown_seconds: int = 1800) -> bool:
    """Check if the cooldown period has NOT elapsed since the last draft.

    Returns True if still cooling down (should NOT create draft).
    """
    cutoff = (clock.now_utc() - timedelta(seconds=cooldown_seconds)).isoformat()
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM x_drafts WHERE created_at > ? AND status != 'rejected'",
        (cutoff,),
    )
    row = await cursor.fetchone()
    return row[0] > 0
