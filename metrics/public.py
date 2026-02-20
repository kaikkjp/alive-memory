"""Public liveness dashboard data generator (TASK-071).

Produces the data for the unauthenticated /api/metrics/public endpoint.
No auth required — this is the "proof of life" page data.
"""

from metrics.collector import collect_all, get_metric_trend


async def get_public_liveness() -> dict:
    """Generate public liveness dashboard data.

    Returns a dict with:
    - status: 'alive' | 'sleeping' | 'unknown'
    - current: latest metric values
    - trends: 30-day trend data per metric
    """
    # Compute live metrics
    snapshot = await collect_all()

    current = {}
    for m in snapshot.metrics:
        current[m.name] = {
            'value': m.value,
            'display': m.display,
            'details': m.details,
        }

    # Get 30-day trends for each metric
    trends = {}
    for metric_name in ('uptime', 'initiative_rate', 'emotional_range'):
        trend_data = await get_metric_trend(metric_name, days=30, period='daily')
        trends[metric_name] = [
            {'timestamp': t['timestamp'], 'value': t['value']}
            for t in trend_data
        ]

    # Determine status
    uptime_data = current.get('uptime', {})
    cycles = uptime_data.get('details', {}).get('cycles', 0)
    status = 'alive' if cycles > 0 else 'unknown'

    return {
        'status': status,
        'timestamp': snapshot.timestamp,
        'current': current,
        'trends': trends,
    }
