-- TASK-105: Drive relief parameters for event-based regulation.

INSERT OR IGNORE INTO self_parameters
  (key, value, default_value, min_bound, max_bound, category, description) VALUES
  ('hypothalamus.event.content_consumed_curiosity_relief', 0.12, 0.12, 0.0, 0.5,
   'hypothalamus', 'Curiosity relief from consuming content');

INSERT OR IGNORE INTO self_parameters
  (key, value, default_value, min_bound, max_bound, category, description) VALUES
  ('hypothalamus.event.thread_updated_expression_relief', 0.10, 0.10, 0.0, 0.5,
   'hypothalamus', 'Expression relief from developing a thread');
