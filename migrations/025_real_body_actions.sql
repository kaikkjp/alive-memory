-- TASK-069: Real-world body actions — external action log + channel config.

-- External action rate limiting log
CREATE TABLE IF NOT EXISTS external_action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 1,
    cost_usd REAL DEFAULT 0,
    channel TEXT,
    error TEXT,
    payload TEXT  -- JSON
);

CREATE INDEX IF NOT EXISTS idx_external_action_ts
    ON external_action_log(action_name, timestamp);

-- Channel configuration (kill switch)
CREATE TABLE IF NOT EXISTS channel_config (
    channel_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    disabled_at TEXT,
    disabled_by TEXT
);

INSERT OR IGNORE INTO channel_config (channel_name, enabled) VALUES
    ('web', 1),
    ('telegram', 0),
    ('x', 0);
