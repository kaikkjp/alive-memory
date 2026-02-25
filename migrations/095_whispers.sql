-- TASK-095 v2: Pending whispers table for sleep whisper system.
-- Manager config changes (Tier 2) are queued here and processed during sleep
-- as dream-like perceptions that the agent integrates organically.

CREATE TABLE IF NOT EXISTS pending_whispers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_path TEXT NOT NULL,       -- e.g. "hypothalamus.equilibria.diversive_curiosity"
    old_value TEXT,                 -- previous value (for perception generation)
    new_value TEXT NOT NULL,        -- target value
    created_at TEXT NOT NULL,       -- ISO timestamp
    processed_at TEXT,              -- NULL until sleep processes it
    dream_text TEXT                 -- the perception generated during sleep
);
