-- Migration 018: Epistemic curiosities + diversive_curiosity rename (TASK-043)

-- Add diversive_curiosity column (alias for curiosity).
-- Keep 'curiosity' column for backward compat with existing schema.
-- The Python DrivesState property alias handles the mapping.
ALTER TABLE drives_state ADD COLUMN diversive_curiosity FLOAT DEFAULT 0.5;

-- Copy existing curiosity value to new column
UPDATE drives_state SET diversive_curiosity = curiosity WHERE id = 1;

-- Create epistemic_curiosities table
CREATE TABLE IF NOT EXISTS epistemic_curiosities (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    question TEXT NOT NULL,
    intensity FLOAT NOT NULL DEFAULT 0.5,
    source_type TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_reinforced_at TEXT NOT NULL,
    decay_rate FLOAT NOT NULL DEFAULT 0.02,
    resolved BOOLEAN NOT NULL DEFAULT 0,
    resolution_source TEXT
);

CREATE INDEX IF NOT EXISTS idx_ec_resolved ON epistemic_curiosities(resolved);
CREATE INDEX IF NOT EXISTS idx_ec_intensity ON epistemic_curiosities(intensity);
