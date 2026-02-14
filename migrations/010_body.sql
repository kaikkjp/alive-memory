-- migrations/010_body.sql
-- Body Phase 2: action logging for multi-intention basal ganglia selection.
-- Phase 3 will add inhibitions table. Phase 4 will add habits table.

CREATE TABLE IF NOT EXISTS action_log (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,           -- 'approved'|'suppressed'|'incapable'|'deferred'|'executed'
    source TEXT NOT NULL DEFAULT 'cortex',   -- 'cortex' | 'habit'
    impulse REAL,
    priority REAL,
    content TEXT,
    target TEXT,
    suppression_reason TEXT,
    energy_cost REAL,
    success BOOLEAN,
    error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_action_log_cycle ON action_log(cycle_id);
CREATE INDEX IF NOT EXISTS idx_action_log_action ON action_log(action);
CREATE INDEX IF NOT EXISTS idx_action_log_status ON action_log(status);
CREATE INDEX IF NOT EXISTS idx_action_log_date ON action_log(created_at);
