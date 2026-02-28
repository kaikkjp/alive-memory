"""M9: Unprompted Memory References.

Source: cycle_log.internal_monologue + cycle_log.dialogue columns.
Calculation: Regex-detect temporal markers and memory references in cortex output,
             excluding cycles where a visitor prompted the recall.

Target: 2-3 unprompted memory references per day after 2 weeks.
"""

import re
from datetime import timedelta
from metrics.models import MetricResult
import clock
import db.connection as _connection


# Patterns indicating unprompted memory references
_MEMORY_PATTERNS = [
    re.compile(r'\byesterday\b', re.IGNORECASE),
    re.compile(r'\blast week\b', re.IGNORECASE),
    re.compile(r'\blast time\b', re.IGNORECASE),
    re.compile(r'\bI remember\b', re.IGNORECASE),
    re.compile(r'\bI recall\b', re.IGNORECASE),
    re.compile(r'\bthe other day\b', re.IGNORECASE),
    re.compile(r'\bback when\b', re.IGNORECASE),
    re.compile(r'\bearlier today\b', re.IGNORECASE),
    re.compile(r'\bthis morning\b', re.IGNORECASE),
    re.compile(r'\breminded me of\b', re.IGNORECASE),
    re.compile(r'\blike that time\b', re.IGNORECASE),
    re.compile(r'\bI was thinking about\b', re.IGNORECASE),
    re.compile(r'\bI noticed before\b', re.IGNORECASE),
]

# Patterns in visitor messages that indicate prompted recall
_PROMPTED_PATTERNS = [
    re.compile(r'\bdo you remember\b', re.IGNORECASE),
    re.compile(r'\bremember when\b', re.IGNORECASE),
    re.compile(r'\blast time we\b', re.IGNORECASE),
    re.compile(r'\byou told me\b', re.IGNORECASE),
    re.compile(r'\byou said\b', re.IGNORECASE),
    re.compile(r'\byou mentioned\b', re.IGNORECASE),
]


def _count_memory_refs(text: str) -> int:
    """Count unique memory reference patterns in a text."""
    if not text:
        return 0
    return sum(1 for p in _MEMORY_PATTERNS if p.search(text))


def _is_prompted(visitor_text: str) -> bool:
    """Check if visitor message prompted the recall."""
    if not visitor_text:
        return False
    return any(p.search(visitor_text) for p in _PROMPTED_PATTERNS)


async def compute(hours: int = 24) -> MetricResult:
    """Compute M9 unprompted memory references over the given time window."""
    conn = await _connection.get_db()
    cutoff = (clock.now_utc() - timedelta(hours=hours)).isoformat()

    # Get cycle logs with monologue and dialogue text
    cursor = await conn.execute(
        """SELECT id, mode, internal_monologue, dialogue, ts
           FROM cycle_log
           WHERE datetime(ts) >= datetime(?)
             AND mode != 'sleep'""",
        (cutoff,),
    )
    rows = await cursor.fetchall()

    total_refs = 0
    unprompted_refs = 0
    cycles_with_refs = 0
    examples = []

    for row in rows:
        monologue = row['internal_monologue'] or ''
        dialogue = row['dialogue'] or ''
        combined = monologue + ' ' + dialogue

        ref_count = _count_memory_refs(combined)
        if ref_count == 0:
            continue

        total_refs += ref_count

        # Check if this was a visitor cycle where recall was prompted
        is_visitor_cycle = (row['mode'] == 'visitor')
        prompted = False

        if is_visitor_cycle:
            # Check recent events for prompted recall patterns
            try:
                ev_cursor = await conn.execute(
                    """SELECT content FROM events
                       WHERE cycle_id = ?
                         AND event_type = 'visitor_message'""",
                    (row['id'],),
                )
                ev_rows = await ev_cursor.fetchall()
                visitor_text = ' '.join(r['content'] or '' for r in ev_rows)
                prompted = _is_prompted(visitor_text)
            except Exception:
                # events table might not have cycle_id or content columns
                pass

        if not prompted:
            unprompted_refs += ref_count
            cycles_with_refs += 1
            if len(examples) < 5:
                # Extract a snippet as example
                for p in _MEMORY_PATTERNS:
                    m = p.search(combined)
                    if m:
                        start = max(0, m.start() - 30)
                        end = min(len(combined), m.end() + 50)
                        snippet = combined[start:end].strip()
                        examples.append({
                            'cycle_id': row['id'],
                            'snippet': f'...{snippet}...',
                            'timestamp': row['ts'],
                        })
                        break

    display = f"{unprompted_refs} unprompted memory references (last {hours}h)"

    return MetricResult(
        name='unprompted_memories',
        value=float(unprompted_refs),
        details={
            'window_hours': hours,
            'total_references': total_refs,
            'unprompted_references': unprompted_refs,
            'prompted_excluded': total_refs - unprompted_refs,
            'cycles_with_refs': cycles_with_refs,
            'total_cycles_scanned': len(rows),
            'examples': examples,
        },
        display=display,
    )


async def compute_lifetime() -> MetricResult:
    """Compute lifetime unprompted memory reference count and daily rate."""
    conn = await _connection.get_db()

    # Get date range
    cursor = await conn.execute(
        "SELECT MIN(ts) as first_ts, MAX(ts) as last_ts FROM cycle_log"
    )
    row = await cursor.fetchone()
    days_alive = 1
    if row and row['first_ts'] and row['last_ts']:
        from datetime import datetime, timezone
        try:
            first = datetime.fromisoformat(str(row['first_ts']).replace('Z', '+00:00'))
            last = datetime.fromisoformat(str(row['last_ts']).replace('Z', '+00:00'))
            days_alive = max(1, (last - first).days + 1)
        except (ValueError, TypeError):
            pass

    # Count all unprompted references
    cursor = await conn.execute(
        """SELECT internal_monologue, dialogue, mode
           FROM cycle_log
           WHERE mode != 'sleep'
             AND (internal_monologue IS NOT NULL OR dialogue IS NOT NULL)"""
    )
    rows = await cursor.fetchall()

    total_refs = 0
    for row in rows:
        combined = (row['internal_monologue'] or '') + ' ' + (row['dialogue'] or '')
        # For lifetime, skip prompted filtering (too expensive to join events for all cycles)
        ref_count = _count_memory_refs(combined)
        total_refs += ref_count

    daily_rate = total_refs / days_alive if days_alive > 0 else 0.0

    return MetricResult(
        name='unprompted_memories',
        value=float(total_refs),
        details={
            'lifetime': True,
            'total_references': total_refs,
            'days_alive': days_alive,
            'daily_rate': round(daily_rate, 2),
        },
        display=f"{total_refs} lifetime memory references ({daily_rate:.1f}/day)",
    )
