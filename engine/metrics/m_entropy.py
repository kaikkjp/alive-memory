"""M3: Behavioral Entropy.

Source: action_log table (action column for executed actions).
Calculation: Shannon entropy of action distribution per time window.

A scripted bot has entropy ~ 0 (same action every cycle).
A random system has max entropy (uniform distribution).
A living system has *structured* entropy — varied but patterned.
"""

import math
from collections import Counter
from datetime import timedelta
from metrics.models import MetricResult
import clock
import db.connection as _connection


def _shannon_entropy(actions: list[str]) -> float:
    """Compute Shannon entropy of an action distribution.

    Returns bits of entropy. Higher = more diverse behavior.
    """
    if not actions:
        return 0.0
    counts = Counter(actions)
    total = sum(counts.values())
    probs = [c / total for c in counts.values()]
    return -sum(p * math.log2(p) for p in probs if p > 0)


def _normalized_entropy(actions: list[str]) -> float:
    """Entropy normalized to [0, 1] relative to maximum possible.

    Max entropy = log2(num_unique_actions). Returns 0 if <= 1 unique action.
    """
    if not actions:
        return 0.0
    n_unique = len(set(actions))
    if n_unique <= 1:
        return 0.0
    raw = _shannon_entropy(actions)
    max_entropy = math.log2(n_unique)
    return raw / max_entropy if max_entropy > 0 else 0.0


async def compute(hours: int = 24) -> MetricResult:
    """Compute M3 behavioral entropy over the given time window."""
    conn = await _connection.get_db()
    cutoff = (clock.now_utc() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

    # Get all executed actions in the window
    cursor = await conn.execute(
        """SELECT al.action, cl.mode
           FROM action_log al
           JOIN cycle_log cl ON al.cycle_id = cl.id
           WHERE al.status = 'executed'
             AND datetime(al.created_at) >= datetime(?)""",
        (cutoff,),
    )
    rows = await cursor.fetchall()

    all_actions = [r['action'] for r in rows]
    self_actions = [r['action'] for r in rows if r['mode'] != 'visitor']
    visitor_actions = [r['action'] for r in rows if r['mode'] == 'visitor']

    overall_entropy = _shannon_entropy(all_actions)
    normalized = _normalized_entropy(all_actions)
    self_entropy = _shannon_entropy(self_actions)
    visitor_entropy = _shannon_entropy(visitor_actions)

    # Action distribution for details
    distribution = dict(Counter(all_actions).most_common(10))

    display = f"Behavioral entropy: {normalized:.2f} (last {hours}h, {len(all_actions)} actions)"

    return MetricResult(
        name='behavioral_entropy',
        value=round(normalized, 4),
        details={
            'window_hours': hours,
            'total_actions': len(all_actions),
            'unique_actions': len(set(all_actions)),
            'raw_entropy_bits': round(overall_entropy, 4),
            'normalized_entropy': round(normalized, 4),
            'self_entropy_bits': round(self_entropy, 4),
            'visitor_entropy_bits': round(visitor_entropy, 4),
            'top_actions': distribution,
        },
        display=display,
    )


async def compute_lifetime() -> MetricResult:
    """Compute lifetime behavioral entropy (all time)."""
    conn = await _connection.get_db()

    cursor = await conn.execute(
        """SELECT action FROM action_log
           WHERE status = 'executed'"""
    )
    rows = await cursor.fetchall()
    actions = [r['action'] for r in rows]

    normalized = _normalized_entropy(actions)
    raw = _shannon_entropy(actions)
    distribution = dict(Counter(actions).most_common(10))

    return MetricResult(
        name='behavioral_entropy',
        value=round(normalized, 4),
        details={
            'window_hours': 0,
            'total_actions': len(actions),
            'unique_actions': len(set(actions)),
            'raw_entropy_bits': round(raw, 4),
            'normalized_entropy': round(normalized, 4),
            'top_actions': distribution,
            'lifetime': True,
        },
        display=f"Lifetime behavioral entropy: {normalized:.2f} ({len(actions)} actions)",
    )
