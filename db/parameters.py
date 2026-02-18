"""db.parameters — Cognitive architecture parameter management.

Per-cycle cached loading. All pipeline constants live in the self_parameters
DB table. The cache is refreshed once at cycle start by heartbeat.

Usage in pipeline modules:
    from db.parameters import p
    value = p('hypothalamus.equilibria.social_hunger')  # sync, no await
"""

import clock
import db.connection as _connection


# Module-level cache — populated by refresh_params_cache(), read by p()
_cache: dict[str, float] = {}

# Expected keys — populated on first refresh, used for validation
_known_keys: set[str] = set()


async def refresh_params_cache() -> dict[str, float]:
    """Load all parameters from DB into module-level cache.

    Called once per cycle at heartbeat start (in run_cycle()).
    Returns the cache dict.
    """
    global _cache, _known_keys
    db = await _connection.get_db()
    cursor = await db.execute("SELECT key, value FROM self_parameters")
    rows = await cursor.fetchall()
    _cache = {row['key']: row['value'] for row in rows}
    if not _known_keys and _cache:
        _known_keys = set(_cache.keys())
    print(f"  [Parameters] Cache refreshed: {len(_cache)} parameters loaded")
    return _cache


def p(key: str) -> float:
    """Get a cached parameter. No DB call, no await. Fast.

    Raises KeyError if key not in cache — fail loud on typos.
    """
    return _cache[key]


def p_or(key: str, default: float) -> float:
    """Get cached param with fallback. For graceful degradation."""
    return _cache.get(key, default)


def validate_cache() -> list[str]:
    """Validate that all expected keys are present in cache.

    Returns list of warnings (empty = healthy).
    Called after refresh to detect seed data gaps.
    """
    warnings = []
    if not _cache:
        warnings.append("Parameter cache is empty — DB may not be initialized")
    if _known_keys:
        missing = _known_keys - set(_cache.keys())
        for key in sorted(missing):
            warnings.append(f"Expected parameter missing from cache: {key}")
    return warnings


async def get_param(key: str) -> dict | None:
    """Get full parameter record from DB (not cache). For dashboard."""
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM self_parameters WHERE key = ?", (key,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return dict(row)


async def get_params_by_category(category: str) -> list[dict]:
    """Get all parameters in a category. For dashboard."""
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM self_parameters WHERE category = ? ORDER BY key",
        (category,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_all_params() -> list[dict]:
    """Get all parameters. For dashboard."""
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM self_parameters ORDER BY category, key"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def set_param(key: str, value: float, modified_by: str = 'operator',
                    reason: str = None) -> dict:
    """Set a parameter value. Enforces bounds. Logs modification.

    Raises ValueError if key unknown or value out of bounds.
    """
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT * FROM self_parameters WHERE key = ?", (key,)
    )
    row = await cursor.fetchone()
    if not row:
        raise ValueError(f"Unknown parameter: {key}")

    record = dict(row)

    # Enforce bounds
    if record['min_bound'] is not None and value < record['min_bound']:
        raise ValueError(
            f"Value {value} below minimum {record['min_bound']} for {key}")
    if record['max_bound'] is not None and value > record['max_bound']:
        raise ValueError(
            f"Value {value} above maximum {record['max_bound']} for {key}")

    old_value = record['value']
    now = clock.now_utc().isoformat()

    # Update parameter
    await _connection._exec_write(
        "UPDATE self_parameters SET value = ?, modified_by = ?, modified_at = ? "
        "WHERE key = ?",
        (value, modified_by, now, key)
    )

    # Log modification
    await _connection._exec_write(
        "INSERT INTO parameter_modifications "
        "(param_key, old_value, new_value, modified_by, reason, ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (key, old_value, value, modified_by, reason, now)
    )

    # Update cache immediately
    _cache[key] = value

    record['value'] = value
    record['modified_by'] = modified_by
    record['modified_at'] = now
    return record


async def reset_param(key: str, modified_by: str = 'operator') -> dict:
    """Reset a parameter to its default value."""
    db = await _connection.get_db()
    cursor = await db.execute(
        "SELECT default_value FROM self_parameters WHERE key = ?", (key,)
    )
    row = await cursor.fetchone()
    if not row:
        raise ValueError(f"Unknown parameter: {key}")

    return await set_param(key, row['default_value'], modified_by,
                           reason='reset to default')


async def get_modification_log(key: str = None, limit: int = 50) -> list[dict]:
    """Get recent modifications. Optionally filtered by key."""
    db = await _connection.get_db()
    if key:
        cursor = await db.execute(
            "SELECT * FROM parameter_modifications WHERE param_key = ? "
            "ORDER BY ts DESC LIMIT ?",
            (key, limit)
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM parameter_modifications ORDER BY ts DESC LIMIT ?",
            (limit,)
        )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_todays_self_modifications() -> list[dict]:
    """Get all self-initiated parameter modifications from today (UTC)."""
    db = await _connection.get_db()
    today_start = clock.now_utc().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    cursor = await db.execute(
        "SELECT * FROM parameter_modifications "
        "WHERE modified_by = 'self' AND ts >= ? ORDER BY ts ASC",
        (today_start,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
