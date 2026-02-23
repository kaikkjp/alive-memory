-- TASK-091 fix: store all metric values at experiment creation time
-- so side-effect detection can compare actual before vs after.
ALTER TABLE meta_experiments ADD COLUMN metrics_snapshot TEXT;  -- JSON dict
