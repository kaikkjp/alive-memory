-- Migration 020: X/Twitter social channel (TASK-057)
-- Drafts queue for human-reviewed posting to X.

CREATE TABLE IF NOT EXISTS x_drafts (
    id TEXT PRIMARY KEY,
    draft_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    fingerprint TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    reviewed_at TIMESTAMP,
    posted_at TIMESTAMP,
    x_post_id TEXT,
    rejection_reason TEXT,
    error_message TEXT,
    cycle_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_x_drafts_status ON x_drafts(status);
CREATE INDEX IF NOT EXISTS idx_x_drafts_fingerprint ON x_drafts(fingerprint);
CREATE INDEX IF NOT EXISTS idx_x_drafts_created_at ON x_drafts(created_at);
