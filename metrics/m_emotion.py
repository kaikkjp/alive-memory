"""M7: Emotional Range.

Source: cycle_log.drives JSON column (contains valence, arousal, energy per cycle).
Calculation: Quantize mood space into bins, count unique bins visited.

The drives JSON in cycle_log contains mood_valence, mood_arousal, and energy.
We quantize each to 5 bins (0.0-0.2, 0.2-0.4, ..., 0.8-1.0) → 5^3 = 125 states.
"""

import json
from metrics.models import MetricResult
import db.connection as _connection


def _quantize(value: float, bins: int = 5) -> int:
    """Quantize a 0-1 float into a bin index."""
    # Clamp to [0, 1]
    v = max(0.0, min(1.0, value))
    idx = int(v * bins)
    # Edge case: value == 1.0 → bin 5, clamp to bin 4
    return min(idx, bins - 1)


def _normalize_valence(v: float) -> float:
    """Normalize mood_valence from [-1, 1] to [0, 1]."""
    return (v + 1.0) / 2.0


async def compute() -> MetricResult:
    """Compute M7 emotional range from cycle_log drives history."""
    conn = await _connection.get_db()

    # Read all drives JSON from cycle_log
    cursor = await conn.execute(
        "SELECT drives FROM cycle_log WHERE drives IS NOT NULL"
    )
    rows = await cursor.fetchall()

    bins_visited = set()
    total_cycles = 0

    for row in rows:
        try:
            drives = json.loads(row['drives']) if isinstance(row['drives'], str) else row['drives']
            if not drives:
                continue

            valence = drives.get('mood_valence', 0.0)
            arousal = drives.get('mood_arousal', 0.3)
            energy = drives.get('energy', 0.8)

            # Normalize valence from [-1,1] to [0,1]
            v_norm = _normalize_valence(valence)

            bin_tuple = (
                _quantize(v_norm),
                _quantize(arousal),
                _quantize(energy),
            )
            bins_visited.add(bin_tuple)
            total_cycles += 1
        except (json.JSONDecodeError, TypeError, KeyError):
            continue

    total_possible = 125  # 5^3
    range_count = len(bins_visited)
    range_pct = (range_count / total_possible * 100.0) if total_possible > 0 else 0.0

    display = f"Emotional range: {range_count}/{total_possible} states experienced"

    return MetricResult(
        name='emotional_range',
        value=float(range_count),
        details={
            'states_visited': range_count,
            'total_possible': total_possible,
            'range_pct': round(range_pct, 1),
            'cycles_analyzed': total_cycles,
        },
        display=display,
    )
