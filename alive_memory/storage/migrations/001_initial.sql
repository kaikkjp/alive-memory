-- alive-memory initial schema
-- Applied automatically on first initialize()

-- Core memories table
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'episodic',
    strength REAL NOT NULL DEFAULT 0.5,
    valence REAL NOT NULL DEFAULT 0.0,
    formed_at TEXT NOT NULL,
    last_recalled TEXT,
    recall_count INTEGER NOT NULL DEFAULT 0,
    source_event TEXT,
    drive_coupling TEXT DEFAULT '{}',
    embedding BLOB,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memories_strength ON memories(strength);
CREATE INDEX IF NOT EXISTS idx_memories_formed ON memories(formed_at);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);

-- Drive state (single row)
CREATE TABLE IF NOT EXISTS drive_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    curiosity REAL NOT NULL DEFAULT 0.5,
    social REAL NOT NULL DEFAULT 0.5,
    expression REAL NOT NULL DEFAULT 0.5,
    rest REAL NOT NULL DEFAULT 0.5,
    updated_at TEXT
);
INSERT OR IGNORE INTO drive_state (id) VALUES (1);

-- Mood state (single row)
CREATE TABLE IF NOT EXISTS mood_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    valence REAL NOT NULL DEFAULT 0.0,
    arousal REAL NOT NULL DEFAULT 0.5,
    word TEXT NOT NULL DEFAULT 'neutral',
    updated_at TEXT
);
INSERT OR IGNORE INTO mood_state (id) VALUES (1);

-- Cognitive state (single row)
CREATE TABLE IF NOT EXISTS cognitive_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    energy REAL NOT NULL DEFAULT 0.8,
    cycle_count INTEGER NOT NULL DEFAULT 0,
    last_sleep TEXT,
    memories_total INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
INSERT OR IGNORE INTO cognitive_state (id) VALUES (1);

-- Self-model (identity)
CREATE TABLE IF NOT EXISTS self_model (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    traits TEXT NOT NULL DEFAULT '{}',
    behavioral_summary TEXT NOT NULL DEFAULT '',
    drift_history TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 0,
    snapshot_at TEXT
);
INSERT OR IGNORE INTO self_model (id) VALUES (1);

-- Self-model snapshots (developmental history)
CREATE TABLE IF NOT EXISTS self_model_snapshots (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    traits TEXT NOT NULL DEFAULT '{}',
    behavioral_summary TEXT NOT NULL DEFAULT '',
    cycle_count INTEGER NOT NULL DEFAULT 0,
    snapshot_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_version ON self_model_snapshots(version);

-- Cognitive parameters (key-value with bounds and history)
CREATE TABLE IF NOT EXISTS parameters (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    default_value REAL NOT NULL,
    min_bound REAL,
    max_bound REAL,
    category TEXT,
    description TEXT,
    modified_by TEXT DEFAULT 'system',
    modified_at TEXT
);

-- Parameter modification log
CREATE TABLE IF NOT EXISTS parameter_modifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_key TEXT NOT NULL,
    old_value REAL,
    new_value REAL NOT NULL,
    modified_by TEXT NOT NULL DEFAULT 'system',
    reason TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_param_mods_key ON parameter_modifications(param_key);
CREATE INDEX IF NOT EXISTS idx_param_mods_ts ON parameter_modifications(ts);

-- Cycle audit log
CREATE TABLE IF NOT EXISTS cycle_log (
    id TEXT PRIMARY KEY,
    cycle_number INTEGER,
    trigger_type TEXT,
    drives TEXT,
    mood TEXT,
    energy REAL,
    memory_count INTEGER,
    actions TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cycle_log_ts ON cycle_log(ts);

-- Consolidation reports
CREATE TABLE IF NOT EXISTS consolidation_log (
    id TEXT PRIMARY KEY,
    memories_strengthened INTEGER DEFAULT 0,
    memories_weakened INTEGER DEFAULT 0,
    memories_pruned INTEGER DEFAULT 0,
    memories_merged INTEGER DEFAULT 0,
    dreams TEXT DEFAULT '[]',
    reflections TEXT DEFAULT '[]',
    identity_drift TEXT,
    duration_ms INTEGER DEFAULT 0,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consolidation_ts ON consolidation_log(ts);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    filename TEXT NOT NULL
);
