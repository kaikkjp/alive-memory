-- TASK-090: Meta-controller experiment log
-- Tracks parameter adjustments made by the meta-controller during sleep.
-- TASK-091 will fill in metric_value_after and outcome fields.

CREATE TABLE IF NOT EXISTS meta_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_at_change INTEGER NOT NULL,
    param_name TEXT NOT NULL,
    old_value REAL NOT NULL,
    new_value REAL NOT NULL,
    reason TEXT NOT NULL,
    target_metric TEXT NOT NULL,
    metric_value_at_change REAL NOT NULL,
    metric_value_after REAL,
    outcome TEXT DEFAULT 'pending',
    reverted_at_cycle INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_meta_exp_param ON meta_experiments(param_name);
CREATE INDEX IF NOT EXISTS idx_meta_exp_cycle ON meta_experiments(cycle_at_change DESC);
CREATE INDEX IF NOT EXISTS idx_meta_exp_outcome ON meta_experiments(outcome);
