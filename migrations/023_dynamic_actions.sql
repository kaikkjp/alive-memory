CREATE TABLE IF NOT EXISTS dynamic_actions (
    action_name       TEXT PRIMARY KEY,
    alias_for         TEXT,
    body_state        TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',
    attempt_count     INTEGER NOT NULL DEFAULT 1,
    promote_threshold INTEGER NOT NULL DEFAULT 5,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    resolved_by       TEXT,
    notes             TEXT
);

-- No seed data. Each agent discovers actions organically.
-- Shopkeeper's historical data (browse_web:242, stand:118, etc.) was
-- previously seeded here but polluted every new agent's DB.
-- Shopkeeper's existing DB already has these rows; new agents start clean.
