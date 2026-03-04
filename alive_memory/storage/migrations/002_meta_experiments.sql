-- Experiment lifecycle tracking
CREATE TABLE IF NOT EXISTS meta_experiments (
    id TEXT PRIMARY KEY,
    param_key TEXT NOT NULL,
    old_value REAL NOT NULL,
    new_value REAL NOT NULL,
    target_metric TEXT NOT NULL,
    metric_at_change REAL NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending',  -- pending/improved/degraded/neutral
    confidence REAL NOT NULL DEFAULT 0.5,
    side_effects TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    evaluated_at TEXT,
    cycle_at_creation INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_meta_exp_outcome ON meta_experiments(outcome);
CREATE INDEX IF NOT EXISTS idx_meta_exp_param ON meta_experiments(param_key);

-- Per param→metric confidence scores (persisted across cycles)
CREATE TABLE IF NOT EXISTS meta_confidence (
    param_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (param_key, metric_name)
);
