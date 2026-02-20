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

INSERT OR IGNORE INTO dynamic_actions (action_name, alias_for, body_state, status, attempt_count, first_seen, last_seen, resolved_by)
VALUES
    ('browse_web', NULL,           NULL,                        'rejected',   242, datetime('now'), datetime('now'), 'seed'),
    ('stand',      NULL,           '{"body_state":"standing_window"}', 'body_state', 118, datetime('now'), datetime('now'), 'seed'),
    ('sit',        NULL,           '{"body_state":"sitting"}',  'body_state',  50, datetime('now'), datetime('now'), 'seed'),
    ('make_tea',   NULL,           NULL,                        'pending',     17, datetime('now'), datetime('now'), NULL);
