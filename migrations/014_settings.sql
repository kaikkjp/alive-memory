-- Settings key-value store for operator-configurable runtime parameters.
-- Used for cycle_interval persistence and future operator settings.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
