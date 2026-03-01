"""Notifications — surface content titles to the cortex as perceptions.

Push model: instead of waiting for an arbiter "consume" cycle, content titles
are surfaced every cycle as background notifications. The cortex sees titles
and can choose to read_content or save_for_later.

Notifications are ephemeral per cycle. If she doesn't engage, they scroll past
and can re-surface after cooldown.
"""

from dataclasses import dataclass
from datetime import datetime

import clock
import db


# ── Configuration ──

NOTIFICATION_CONFIG = {
    'max_per_cycle': 5,
    'min_per_cycle': 1,
    'cooldown_minutes': 10,
}


@dataclass
class Notification:
    """A content item surfaced as a title-only notification."""
    content_id: str
    title: str
    source: str
    content_type: str
    surfaced_at: datetime
    salience_base: float = 0.2


async def get_notifications(cycle_id: str = None) -> list[Notification]:
    """Get notifications to surface this cycle.

    Pulls from content_pool respecting cooldowns. Saved items get priority
    and skip cooldown. Tracks surfaced items in notification_log.
    Returns title-only — no full content loaded.
    """
    # Expire stale saved items (>48h old)
    try:
        await db.expire_saved_items(max_age_hours=48.0)
    except Exception:
        pass  # table may not exist yet

    # Get candidates from content pool
    try:
        candidates = await db.get_notification_candidates(
            max_items=NOTIFICATION_CONFIG['max_per_cycle'],
            cooldown_minutes=NOTIFICATION_CONFIG['cooldown_minutes'],
        )
    except Exception:
        return []  # graceful degradation if tables don't exist yet

    if not candidates:
        return []

    now = clock.now_utc()
    notifications = []

    for item in candidates:
        title = item.get('title') or '(untitled)'
        source = item.get('source_channel') or item.get('source_type') or 'unknown'
        content_type = item.get('content_type') or item.get('source_type') or 'article'

        notification = Notification(
            content_id=item['id'],
            title=title,
            source=source,
            content_type=content_type,
            surfaced_at=now,
            salience_base=item.get('salience_base', 0.2),
        )
        notifications.append(notification)

        # Log that we surfaced this item
        try:
            await db.log_notification_surfaced(item['id'], cycle_id)
        except Exception:
            pass  # don't fail the cycle over logging

    return notifications


def format_notifications_text(notifications: list[Notification],
                               visitor_present: bool = False,
                               gap_scores: dict = None) -> str:
    """Format notifications as diegetic text for the sensorium.

    When a visitor is present, notifications are marked as background.
    gap_scores: Optional dict mapping content_id -> GapScore for annotations.
    """
    if not notifications:
        return ''

    from pipeline.gap_detector import format_gap_annotation

    lines = []
    for n in notifications:
        line = f'  \u2022 "{n.title}" ({n.source}) \u2014 {n.content_type} [id:{n.content_id}]'

        # TASK-042: Add gap annotation if available
        if gap_scores and n.content_id in gap_scores:
            gs = gap_scores[n.content_id]
            annotation = format_gap_annotation(gs)
            if annotation:
                line += f'\n      {annotation}'

        lines.append(line)

    items_text = '\n'.join(lines)

    if visitor_present:
        return (
            f"(In the background, you notice some things in your feed:\n"
            f"{items_text}\n"
            f"  You could read_content(content_id) or save_for_later(content_id) later.)"
        )
    else:
        return (
            f"You notice some things in your feed:\n"
            f"{items_text}\n"
            f"  You could read_content(content_id) or save_for_later(content_id)."
        )
