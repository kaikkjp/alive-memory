-- Migration 017: Gap detection support (TASK-042)
-- Add title_embedding column to content_pool for pre-embedded notification titles.

ALTER TABLE content_pool ADD COLUMN title_embedding BLOB;
