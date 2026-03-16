-- Unified cold memory: events, totems, and traits in one searchable archive
-- Replaces separate cold_embeddings + keyword-only totem/trait search
-- All entries are embedded for semantic retrieval at query time

CREATE TABLE IF NOT EXISTS cold_memory (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,          -- readable text for display
    raw_content TEXT,               -- original event text (NULL for totems/traits)
    embedding BLOB,                 -- serialized float vector (OpenAI text-embedding-3-small)
    entry_type TEXT NOT NULL DEFAULT 'event',  -- "event", "totem", "trait"
    visitor_id TEXT,                -- NULL for global entries
    weight REAL NOT NULL DEFAULT 1.0,  -- totem weight or trait confidence
    category TEXT NOT NULL DEFAULT '',  -- totem/trait category
    metadata TEXT NOT NULL DEFAULT '{}',  -- JSON (event_type, salience, valence, etc.)
    source_moment_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cold_memory_type ON cold_memory(entry_type);
CREATE INDEX IF NOT EXISTS idx_cold_memory_visitor ON cold_memory(visitor_id);
CREATE INDEX IF NOT EXISTS idx_cold_memory_created ON cold_memory(created_at);
