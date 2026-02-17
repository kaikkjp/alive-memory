-- Migration 019: Consumption tracking (TASK-044)
-- Add consumed tracking columns to content_pool.

ALTER TABLE content_pool ADD COLUMN consumed BOOLEAN DEFAULT 0;
ALTER TABLE content_pool ADD COLUMN consumed_at TEXT;
ALTER TABLE content_pool ADD COLUMN consumption_output TEXT;
