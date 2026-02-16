-- TASK-038: Add nap_processed flag to day_memory
-- Moments processed during naps are excluded from night sleep consolidation.
ALTER TABLE day_memory ADD COLUMN nap_processed INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_day_memory_nap ON day_memory(nap_processed) WHERE nap_processed = 0;
