-- TASK-071: Liveness metrics — Phase 1
-- Stores metric snapshots for M1 (uptime), M2 (initiative rate), M7 (emotional range)

CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    details TEXT,           -- JSON blob with breakdown
    period TEXT DEFAULT 'hourly'  -- hourly | daily | lifetime
);

CREATE INDEX IF NOT EXISTS idx_metrics_name_time
    ON metrics_snapshots(metric_name, timestamp);

CREATE INDEX IF NOT EXISTS idx_metrics_period
    ON metrics_snapshots(period, timestamp);
