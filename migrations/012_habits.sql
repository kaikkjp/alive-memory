-- Migration 012: Habit tracking
-- Tracks repeated action patterns to form habits

CREATE TABLE IF NOT EXISTS habits (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    trigger_context TEXT NOT NULL DEFAULT '{}',
    strength REAL NOT NULL DEFAULT 0.1,
    repetition_count INTEGER NOT NULL DEFAULT 1,
    formed_at TIMESTAMP NOT NULL,
    last_triggered TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_habits_action ON habits(action);
CREATE INDEX IF NOT EXISTS idx_habits_strength ON habits(strength);
