-- 005: Consolidation improvement — source_moment_id indexes
--
-- S7: Index source_moment_id across all tables for provenance joins

CREATE INDEX IF NOT EXISTS idx_cold_memory_source ON cold_memory(source_moment_id);
CREATE INDEX IF NOT EXISTS idx_totems_source_moment ON totems(source_moment_id);
CREATE INDEX IF NOT EXISTS idx_traits_source_moment ON visitor_traits(source_moment_id);
