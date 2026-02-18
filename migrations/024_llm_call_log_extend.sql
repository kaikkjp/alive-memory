-- Extend llm_call_log table with OpenRouter tracking fields
ALTER TABLE llm_call_log ADD COLUMN call_site TEXT;
ALTER TABLE llm_call_log ADD COLUMN latency_ms INTEGER;
