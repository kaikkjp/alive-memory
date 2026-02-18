-- Migration 020: Clear self_assessment inhibitions (TASK-054)
-- Removes inhibitions formed from internal self-doubt (cortex introspection).
-- These were incorrectly silencing write_journal and express_thought.
-- Safe to run on prod: inhibitions formed from visitor_displeasure have
-- 'visitor_displeasure' in their reason JSON, not 'self_assessment'.

DELETE FROM inhibitions WHERE reason LIKE '%self_assessment%';
