-- TASK-095 v3.1 Batch 1: Per-agent RSS feed configuration
CREATE TABLE IF NOT EXISTS agent_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    label TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    poll_interval_minutes INTEGER NOT NULL DEFAULT 60,
    last_fetched_at TEXT,
    items_fetched INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
