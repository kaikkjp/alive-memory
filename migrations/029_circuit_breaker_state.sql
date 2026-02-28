-- TASK-075: Circuit breaker persistence (schema only)
-- Table schema for circuit breaker state persistence across restarts.
-- Runtime state is authoritative (in-memory dict in basal_ganglia.py).
-- NOTE: DB load/save hooks are NOT yet implemented — state is currently
-- lost on restart. A follow-up task should add startup load + on-change
-- save in basal_ganglia.py using this table.

CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    action_name TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'closed',          -- 'closed' | 'open' | 'half_open'
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_failure_time TEXT,                         -- ISO 8601 UTC
    cooldown_seconds REAL NOT NULL DEFAULT 300.0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
