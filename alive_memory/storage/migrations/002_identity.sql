-- Identity system enhancement: drift baselines + evolution log

-- Drift baseline (single row)
CREATE TABLE IF NOT EXISTS drift_baseline (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    action_frequencies TEXT NOT NULL DEFAULT '{}',
    scalar_metrics TEXT NOT NULL DEFAULT '{}',
    sample_count INTEGER NOT NULL DEFAULT 0,
    last_updated_cycle INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
INSERT OR IGNORE INTO drift_baseline (id) VALUES (1);

-- Evolution decision log
CREATE TABLE IF NOT EXISTS evolution_log (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    trait TEXT NOT NULL,
    reason TEXT NOT NULL,
    correction_value REAL,
    composite_score REAL,
    severity TEXT,
    cycle INTEGER,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evolution_ts ON evolution_log(ts);
CREATE INDEX IF NOT EXISTS idx_evolution_trait ON evolution_log(trait);
