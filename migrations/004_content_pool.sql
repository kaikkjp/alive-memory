-- Content pool for reading, news, and visitor drops
CREATE TABLE IF NOT EXISTS content_pool (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_channel TEXT NOT NULL,
    content TEXT NOT NULL,
    title TEXT,
    metadata JSON DEFAULT '{}',
    source_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'unseen',
    salience_base FLOAT DEFAULT 0.2,
    added_at TIMESTAMP NOT NULL,
    seen_at TIMESTAMP,
    engaged_at TIMESTAMP,
    outcome_detail TEXT,
    tags JSON DEFAULT '[]',
    ttl_hours FLOAT DEFAULT 4.0
);
CREATE INDEX IF NOT EXISTS idx_pool_status ON content_pool(status, added_at);
CREATE INDEX IF NOT EXISTS idx_pool_source ON content_pool(source_channel);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pool_fingerprint ON content_pool(fingerprint);
