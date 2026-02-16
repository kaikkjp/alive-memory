-- Add enrichment columns to content_pool for markdown.new integration
ALTER TABLE content_pool ADD COLUMN enriched_text TEXT;
ALTER TABLE content_pool ADD COLUMN content_type TEXT DEFAULT 'article';
