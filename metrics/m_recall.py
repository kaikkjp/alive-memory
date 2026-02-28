"""M5: Visitor Memory Accuracy.

Source: visitors table (visit_count for returning visitors) +
        data/memory/visitors/ MD files (existence = active recall) +
        recall_injection_log (structured recall events).

Proxy metric: visitors_with_memory_file / total_returning_visitors.
Target: >75% for visitors with 3+ conversations.
"""

import os
from metrics.models import MetricResult
import db.connection as _connection


async def compute(min_visits: int = 2) -> MetricResult:
    """Compute M5 visitor memory accuracy.

    Args:
        min_visits: minimum visit_count to consider a "returning" visitor.
    """
    conn = await _connection.get_db()

    # Get returning visitors
    cursor = await conn.execute(
        """SELECT id, name, visit_count, summary
           FROM visitors
           WHERE visit_count >= ?""",
        (min_visits,),
    )
    returning = await cursor.fetchall()
    total_returning = len(returning)

    if total_returning == 0:
        return MetricResult(
            name='visitor_recall',
            value=0.0,
            details={
                'total_returning': 0,
                'remembered': 0,
                'recall_rate_pct': 0.0,
                'min_visits': min_visits,
            },
            display='No returning visitors yet',
        )

    # Check which returning visitors have a memory file
    visitors_dir = os.path.join('data', 'memory', 'visitors')
    remembered = 0
    visitor_details = []

    for v in returning:
        vid = v['id']
        has_file = False
        if os.path.isdir(visitors_dir):
            # Check for MD file with visitor ID in the name
            for fname in os.listdir(visitors_dir):
                if vid in fname and fname.endswith('.md'):
                    has_file = True
                    break

        # Also check recall_injection_log for this visitor
        has_injection = False
        try:
            cursor = await conn.execute(
                """SELECT COUNT(*) as cnt FROM recall_injection_log
                   WHERE payload_json LIKE ?""",
                (f'%{vid}%',),
            )
            row = await cursor.fetchone()
            has_injection = (row['cnt'] > 0) if row else False
        except Exception:
            # Table may not exist yet
            pass

        # Also check if visitor has a summary (basic recall)
        has_summary = bool(v['summary'])

        is_remembered = has_file or has_injection or has_summary
        if is_remembered:
            remembered += 1

        visitor_details.append({
            'id': vid,
            'name': v['name'],
            'visits': v['visit_count'],
            'has_memory_file': has_file,
            'has_recall_injection': has_injection,
            'has_summary': has_summary,
            'remembered': is_remembered,
        })

    recall_rate = (remembered / total_returning * 100.0) if total_returning > 0 else 0.0

    display = f"Remembers {remembered}/{total_returning} returning visitors ({recall_rate:.0f}%)"

    return MetricResult(
        name='visitor_recall',
        value=round(recall_rate, 2),
        details={
            'total_returning': total_returning,
            'remembered': remembered,
            'recall_rate_pct': round(recall_rate, 2),
            'min_visits': min_visits,
            'visitors': visitor_details[:20],  # cap detail size
        },
        display=display,
    )
