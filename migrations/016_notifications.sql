-- Migration 016: Notification layer (TASK-041)
-- Adds notification_log table for tracking surfaced content
-- Adds saved_by_cortex and saved_at columns to content_pool

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id TEXT NOT NULL,
    surfaced_at TEXT NOT NULL,
    cycle_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_notification_log_content_id
    ON notification_log(content_id);

CREATE INDEX IF NOT EXISTS idx_notification_log_surfaced_at
    ON notification_log(surfaced_at);

-- Add saved_by_cortex and saved_at to content_pool
ALTER TABLE content_pool ADD COLUMN saved_by_cortex BOOLEAN DEFAULT 0;
ALTER TABLE content_pool ADD COLUMN saved_at TEXT;
