-- TASK: Evidence-pack observability wiring
-- Additive tables only (existing-table columns are handled by add_column_if_missing at startup)

CREATE TABLE IF NOT EXISTS run_registry (
    run_id TEXT PRIMARY KEY,
    model_name TEXT,
    commit_hash TEXT,
    config_hash TEXT,
    seed INTEGER,
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    status TEXT DEFAULT 'running',
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_run_registry_started
    ON run_registry(started_at_utc);

CREATE TABLE IF NOT EXISTS runtime_event_log (
    id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    cycle_id TEXT,
    event_type TEXT NOT NULL,
    error_type TEXT,
    stack_hash TEXT,
    state_hash TEXT,
    payload_json TEXT,
    trace_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_runtime_event_time
    ON runtime_event_log(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_runtime_event_run
    ON runtime_event_log(run_id, event_type);
CREATE INDEX IF NOT EXISTS idx_runtime_event_cycle
    ON runtime_event_log(cycle_id);

CREATE TABLE IF NOT EXISTS memory_write_log (
    id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    cycle_id TEXT,
    sleep_session_id TEXT,
    memory_type TEXT NOT NULL,
    tokens_written INTEGER DEFAULT 0,
    size_bytes INTEGER DEFAULT 0,
    source TEXT NOT NULL,
    content_hash TEXT,
    fact_id TEXT,
    location TEXT,
    trace_id TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_write_time
    ON memory_write_log(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_memory_write_run
    ON memory_write_log(run_id, source);
CREATE INDEX IF NOT EXISTS idx_memory_write_cycle
    ON memory_write_log(cycle_id);
CREATE INDEX IF NOT EXISTS idx_memory_write_fact
    ON memory_write_log(fact_id);

CREATE TABLE IF NOT EXISTS recall_injection_log (
    id TEXT PRIMARY KEY,
    injection_time_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    cycle_id TEXT,
    fact_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    injection_channel TEXT,
    trace_id TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_recall_injection_time
    ON recall_injection_log(injection_time_utc);
CREATE INDEX IF NOT EXISTS idx_recall_injection_fact
    ON recall_injection_log(fact_id);
CREATE INDEX IF NOT EXISTS idx_recall_injection_run
    ON recall_injection_log(run_id);

CREATE TABLE IF NOT EXISTS recall_test_log (
    id TEXT PRIMARY KEY,
    test_time_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    cycle_id TEXT,
    question_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    retrieved INTEGER NOT NULL,
    answer_correctness_score REAL NOT NULL,
    used_in_answer INTEGER,
    horizon_hours INTEGER,
    trace_id TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_recall_test_time
    ON recall_test_log(test_time_utc);
CREATE INDEX IF NOT EXISTS idx_recall_test_fact
    ON recall_test_log(fact_id);
CREATE INDEX IF NOT EXISTS idx_recall_test_run
    ON recall_test_log(run_id);
