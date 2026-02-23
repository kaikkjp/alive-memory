-- TASK-091: Closed-loop self-evaluation — confidence tracking
-- Extends meta_experiments with evaluation fields and adds learned confidence table.

-- Extend meta_experiments table with evaluation columns
ALTER TABLE meta_experiments ADD COLUMN evaluation_cycle INTEGER;
ALTER TABLE meta_experiments ADD COLUMN side_effects TEXT;       -- JSON array
ALTER TABLE meta_experiments ADD COLUMN confidence_at_change REAL;

-- Learned confidence per param→metric link
CREATE TABLE IF NOT EXISTS meta_confidence (
    param_name TEXT NOT NULL,
    target_metric TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    improved INTEGER DEFAULT 0,
    degraded INTEGER DEFAULT 0,
    neutral INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    avg_effect_size REAL DEFAULT 0.0,
    last_updated_cycle INTEGER,
    PRIMARY KEY (param_name, target_metric)
);
