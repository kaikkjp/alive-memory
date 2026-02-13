-- Migration 003: Threads table for inner agenda (Living Loop Phase 2)

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    thread_type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    priority FLOAT NOT NULL DEFAULT 0.5,
    content TEXT,
    resolution TEXT,
    created_at TIMESTAMP NOT NULL,
    last_touched TIMESTAMP NOT NULL,
    touch_count INTEGER DEFAULT 0,
    touch_reason TEXT,
    target_date TEXT,
    source_visitor_id TEXT,
    source_event_id TEXT,
    tags JSON DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_threads_touched ON threads(last_touched);
