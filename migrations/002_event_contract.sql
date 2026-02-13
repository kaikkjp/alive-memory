-- Migration 002: Extend events table with channel, salience, TTL, outcome fields.
-- Uses Python helper add_column_if_missing() — this file is a marker;
-- column additions are handled by the migration runner's Python path
-- because SQLite lacks ADD COLUMN IF NOT EXISTS.

-- Marker: columns to add are:
--   channel TEXT DEFAULT 'system'
--   salience_base FLOAT DEFAULT 0.5
--   salience_dynamic FLOAT DEFAULT 0.0
--   ttl_hours FLOAT
--   engaged_at TIMESTAMP
--   outcome TEXT

-- The migration runner detects this file and calls add_column_if_missing()
-- for each column listed above. See db.py run_migrations().
