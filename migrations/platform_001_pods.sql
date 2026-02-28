-- Platform-level pod registry (supervisor/registry.py)
-- Database: data/supervisor.db (separate from per-agent DBs and lounge.db)

CREATE TABLE IF NOT EXISTS pods (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'creating',
    port INTEGER UNIQUE,
    container_id TEXT,

    -- Resource limits
    openrouter_key_hash TEXT NOT NULL DEFAULT '',
    memory_limit_mb INTEGER NOT NULL DEFAULT 512,
    cpu_limit REAL NOT NULL DEFAULT 0.5,
    data_dir TEXT NOT NULL,

    -- Health
    health_status TEXT NOT NULL DEFAULT 'unknown',
    health_reason TEXT,
    last_health_check TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    restart_count INTEGER NOT NULL DEFAULT 0,

    -- Ownership (passthrough from lounge — supervisor does not validate)
    manager_id TEXT,

    -- Timestamps (UTC ISO8601)
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    started_at TEXT,
    stopped_at TEXT
);

CREATE TABLE IF NOT EXISTS pod_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pod_id TEXT NOT NULL REFERENCES pods(id),
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_pod_events_pod_id ON pod_events(pod_id);
CREATE INDEX IF NOT EXISTS idx_pod_events_created_at ON pod_events(created_at);
CREATE INDEX IF NOT EXISTS idx_pods_state ON pods(state);
CREATE INDEX IF NOT EXISTS idx_pods_port ON pods(port);
