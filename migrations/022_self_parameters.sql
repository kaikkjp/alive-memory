-- Migration 020: Self-parameters table for cognitive architecture constants.
-- Enables per-cycle cached loading and TASK-056 self-modification.
-- All ~85 hardcoded pipeline constants extracted here as the single source of truth.

CREATE TABLE IF NOT EXISTS self_parameters (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    default_value REAL NOT NULL,
    min_bound REAL,
    max_bound REAL,
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    modified_by TEXT NOT NULL DEFAULT 'seed',
    modified_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_params_category ON self_parameters(category);

CREATE TABLE IF NOT EXISTS parameter_modifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_key TEXT NOT NULL,
    old_value REAL NOT NULL,
    new_value REAL NOT NULL,
    modified_by TEXT NOT NULL,
    reason TEXT,
    ts TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_param_mods_key ON parameter_modifications(param_key);
CREATE INDEX IF NOT EXISTS idx_param_mods_ts ON parameter_modifications(ts DESC);

-- ═══════════════════════════════════════════════════════════════════
-- SEED DATA: All cognitive architecture parameters with defaults
-- ═══════════════════════════════════════════════════════════════════

-- ── hypothalamus: Drive equilibria ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.equilibria.social_hunger', 0.45, 0.45, 0.0, 1.0, 'hypothalamus', 'Social hunger resting point — comfortable alone, not a recluse');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.equilibria.diversive_curiosity', 0.40, 0.40, 0.0, 1.0, 'hypothalamus', 'Diversive curiosity resting point — background scanning urge');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.equilibria.expression_need', 0.35, 0.35, 0.0, 1.0, 'hypothalamus', 'Expression need resting point — expresses when moved');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.equilibria.rest_need', 0.25, 0.25, 0.0, 1.0, 'hypothalamus', 'Rest need resting point — generally rested');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.equilibria.energy', 0.70, 0.70, 0.0, 1.0, 'hypothalamus', 'Energy resting point — alert by default');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.equilibria.mood_valence', 0.05, 0.05, -1.0, 1.0, 'hypothalamus', 'Mood valence resting point — slightly positive neutral');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.equilibria.mood_arousal', 0.30, 0.30, 0.0, 1.0, 'hypothalamus', 'Mood arousal resting point — calm baseline');

-- ── hypothalamus: Homeostatic pull ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.homeostatic_pull_rate', 0.15, 0.15, 0.01, 1.0, 'hypothalamus', 'How fast drives revert to equilibrium per hour');

-- ── hypothalamus: Time-based decay/buildup rates ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.time_decay.social_hunger_per_hour', 0.05, 0.05, 0.0, 0.5, 'hypothalamus', 'Social hunger buildup rate per hour');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.time_decay.curiosity_per_hour', 0.02, 0.02, 0.0, 0.1, 'hypothalamus', 'Diversive curiosity background restlessness per hour');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.time_decay.expression_per_hour', 0.04, 0.04, 0.0, 0.5, 'hypothalamus', 'Expression need buildup rate per hour');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.time_decay.rest_engaged_per_hour', 0.06, 0.06, 0.0, 0.5, 'hypothalamus', 'Rest need buildup when engaged with visitor');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.time_decay.rest_idle_per_hour', 0.03, 0.03, 0.0, 0.5, 'hypothalamus', 'Rest need buildup when idle/alone');

-- ── hypothalamus: Event-based drive effects ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.visitor_speech_social_relief', 0.08, 0.08, 0.0, 0.5, 'hypothalamus', 'Social hunger reduction per visitor speech');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.visitor_speech_rest_cost', 0.04, 0.04, 0.0, 0.5, 'hypothalamus', 'Rest need increase per visitor speech');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.action_speak_expression_relief', 0.05, 0.05, 0.0, 0.5, 'hypothalamus', 'Expression relief when speaking');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.visitor_connect_arousal', 0.1, 0.1, 0.0, 0.5, 'hypothalamus', 'Arousal spike on visitor connection');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.visitor_disconnect_arousal', -0.05, -0.05, -0.5, 0.0, 'hypothalamus', 'Arousal drop on visitor disconnect');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.visitor_disconnect_social', 0.03, 0.03, 0.0, 0.5, 'hypothalamus', 'Social hunger spike on goodbye');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.content_consumed_arousal', 0.05, 0.05, 0.0, 0.5, 'hypothalamus', 'Arousal from reading content');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.thread_updated_arousal', 0.04, 0.04, 0.0, 0.5, 'hypothalamus', 'Arousal from developing an idea');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.event.action_variety_arousal', 0.03, 0.03, 0.0, 0.5, 'hypothalamus', 'Novelty bump from diverse actions');

-- ── hypothalamus: Resonance effects ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.resonance.social_relief', 0.15, 0.15, 0.0, 0.5, 'hypothalamus', 'Bonus social hunger relief on resonance');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.resonance.valence_boost', 0.1, 0.1, 0.0, 0.5, 'hypothalamus', 'Mood valence boost on resonance');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.resonance.arousal_boost', 0.08, 0.08, 0.0, 0.5, 'hypothalamus', 'Arousal spike on resonance');

-- ── hypothalamus: Conversation curiosity suppression ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.conversation.curiosity_suppress_per_hour', 0.02, 0.02, 0.0, 0.2, 'hypothalamus', 'Diversive curiosity suppression during visitor conversation');

-- ── hypothalamus: Drive-to-mood coupling (TASK-046) ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.social_valence_threshold', 0.4, 0.4, 0.0, 1.0, 'hypothalamus', 'Social hunger level triggering mood pressure');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.social_valence_pressure', -0.02, -0.02, -0.2, 0.0, 'hypothalamus', 'Valence pressure per unit above threshold');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.social_valence_floor', 0.15, 0.15, -1.0, 1.0, 'hypothalamus', 'Minimum mood from social pressure alone');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.visitor_relief_factor', 0.05, 0.05, 0.0, 0.3, 'hypothalamus', 'Valence recovery factor when engaged with visitor');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.idle_arousal_threshold', 5.0, 5.0, 1.0, 20.0, 'hypothalamus', 'Consecutive idle cycles before arousal decay');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.idle_arousal_pressure', -0.01, -0.01, -0.1, 0.0, 'hypothalamus', 'Arousal decay per idle cycle above threshold');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.idle_arousal_cap', -0.05, -0.05, -0.5, 0.0, 'hypothalamus', 'Max arousal pressure per cycle');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.visitor_connect_extra_arousal', 0.2, 0.2, 0.0, 0.5, 'hypothalamus', 'Extra arousal on visitor connect (TASK-046)');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.gap_detection_arousal', 0.1, 0.1, 0.0, 0.5, 'hypothalamus', 'Arousal from partial gap detection');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.thread_breakthrough_arousal', 0.15, 0.15, 0.0, 0.5, 'hypothalamus', 'Arousal from idea breakthrough');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.expression_frustration_threshold', 0.5, 0.5, 0.0, 1.0, 'hypothalamus', 'Expression need level triggering valence dip');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.coupling.expression_frustration_pressure', -0.01, -0.01, -0.1, 0.0, 'hypothalamus', 'Valence pressure per unit above expression threshold');

-- ── hypothalamus: Expression relief (immediate post-action) ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.expression_relief.speak_expression', -0.05, -0.05, -0.5, 0.0, 'hypothalamus', 'Expression relief from speaking');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.expression_relief.speak_social', -0.03, -0.03, -0.5, 0.0, 'hypothalamus', 'Social hunger relief from speaking');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.expression_relief.write_journal_expression', -0.12, -0.12, -0.5, 0.0, 'hypothalamus', 'Expression relief from journaling');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.expression_relief.write_journal_rest', 0.02, 0.02, 0.0, 0.2, 'hypothalamus', 'Rest cost from journaling');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.expression_relief.write_journal_skipped_expression', -0.06, -0.06, -0.5, 0.0, 'hypothalamus', 'Expression relief from skipped journal');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.expression_relief.post_x_expression', -0.10, -0.10, -0.5, 0.0, 'hypothalamus', 'Expression relief from posting');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.expression_relief.post_x_rest', 0.02, 0.02, 0.0, 0.2, 'hypothalamus', 'Rest cost from posting');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('hypothalamus.expression_relief.rearrange_expression', -0.06, -0.06, -0.5, 0.0, 'hypothalamus', 'Expression relief from rearranging');

-- ═══ thalamus ═══

-- ── thalamus: Routing thresholds ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.routing.connect_salience_threshold', 0.5, 0.5, 0.0, 1.0, 'thalamus', 'Visitor connect salience threshold for engage');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.routing.silence_salience_threshold', 0.4, 0.4, 0.0, 1.0, 'thalamus', 'Visitor silence salience threshold for engage');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.routing.express_drive_threshold', 0.7, 0.7, 0.0, 1.0, 'thalamus', 'Expression need threshold for express cycle');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.routing.rest_drive_threshold', 0.7, 0.7, 0.0, 1.0, 'thalamus', 'Rest need threshold for rest cycle');

-- ── thalamus: Token budgets ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.budget.flashbulb_daily_limit', 5.0, 5.0, 1.0, 20.0, 'thalamus', 'Max flashbulb moments per day');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.budget.flashbulb_tokens', 10000.0, 10000.0, 1000.0, 20000.0, 'thalamus', 'Token budget for flashbulb (salience > 0.8)');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.budget.deep_tokens', 5000.0, 5000.0, 1000.0, 15000.0, 'thalamus', 'Token budget for deep conversation (salience > 0.6)');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.budget.casual_tokens', 3000.0, 3000.0, 1000.0, 10000.0, 'thalamus', 'Token budget for casual interaction');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.budget.autonomous_tokens', 3000.0, 3000.0, 1000.0, 10000.0, 'thalamus', 'Token budget when alone');

-- ── thalamus: Memory request parameters ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.memory.totem_max_large', 5.0, 5.0, 1.0, 20.0, 'thalamus', 'Max totems at high budget');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.memory.totem_max_small', 3.0, 3.0, 1.0, 10.0, 'thalamus', 'Max totems at low budget');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.memory.totem_min_weight_large', 0.3, 0.3, 0.0, 1.0, 'thalamus', 'Min totem weight at high budget');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.memory.totem_min_weight_small', 0.6, 0.6, 0.0, 1.0, 'thalamus', 'Min totem weight at low budget');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.memory.day_context_salience_engage', 0.3, 0.3, 0.0, 1.0, 'thalamus', 'Min salience for day context in engage');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.memory.day_context_salience_idle', 0.5, 0.5, 0.0, 1.0, 'thalamus', 'Min salience for day context in idle/express');

-- ── thalamus: Notification salience ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.notification.salience_threshold', 0.03, 0.03, 0.0, 0.5, 'thalamus', 'Gap-aware notification salience floor');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.notification.visitor_suppress', 0.3, 0.3, 0.0, 1.0, 'thalamus', 'Salience multiplier when visitor present');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.notification.topic_match_boost', 1.5, 1.5, 1.0, 3.0, 'thalamus', 'Salience multiplier when topic matches conversation');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.notification.low_energy_suppress', 0.2, 0.2, 0.0, 1.0, 'thalamus', 'Salience multiplier when energy < 0.2');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('thalamus.notification.high_curiosity_boost', 1.3, 1.3, 1.0, 3.0, 'thalamus', 'Salience multiplier when curiosity > 0.6');

-- ═══ sensorium ═══

-- ── sensorium: Visitor speech salience ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.base', 0.5, 0.5, 0.0, 1.0, 'sensorium', 'Base salience for visitor speech');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.trust_stranger', 0.0, 0.0, 0.0, 0.5, 'sensorium', 'Trust bonus: stranger');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.trust_returner', 0.1, 0.1, 0.0, 0.5, 'sensorium', 'Trust bonus: returner');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.trust_regular', 0.2, 0.2, 0.0, 0.5, 'sensorium', 'Trust bonus: regular');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.trust_familiar', 0.3, 0.3, 0.0, 0.5, 'sensorium', 'Trust bonus: familiar');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.gift_bonus', 0.2, 0.2, 0.0, 0.5, 'sensorium', 'Salience bonus for gifts/URLs');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.question_bonus', 0.1, 0.1, 0.0, 0.5, 'sensorium', 'Salience bonus for questions');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.personal_bonus', 0.15, 0.15, 0.0, 0.5, 'sensorium', 'Salience bonus for personal questions');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.social_hunger_bonus', 0.15, 0.15, 0.0, 0.5, 'sensorium', 'Bonus when social hunger > 0.7');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.salience.low_energy_penalty', -0.1, -0.1, -0.5, 0.0, 'sensorium', 'Penalty when energy < 0.3');

-- ── sensorium: Visitor connect salience ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.base', 0.3, 0.3, 0.0, 1.0, 'sensorium', 'Base connect salience');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.trust_stranger', 0.0, 0.0, 0.0, 0.5, 'sensorium', 'Connect trust bonus: stranger');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.trust_returner', 0.15, 0.15, 0.0, 0.5, 'sensorium', 'Connect trust bonus: returner');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.trust_regular', 0.3, 0.3, 0.0, 0.5, 'sensorium', 'Connect trust bonus: regular');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.trust_familiar', 0.45, 0.45, 0.0, 0.5, 'sensorium', 'Connect trust bonus: familiar');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.social_hunger_high_bonus', 0.2, 0.2, 0.0, 0.5, 'sensorium', 'Connect bonus when social hunger > 0.7');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.social_hunger_mid_bonus', 0.1, 0.1, 0.0, 0.5, 'sensorium', 'Connect bonus when social hunger > 0.4');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.expression_penalty', -0.15, -0.15, -0.5, 0.0, 'sensorium', 'Connect penalty when absorbed (expression > 0.7)');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.connect.low_energy_penalty', -0.1, -0.1, -0.5, 0.0, 'sensorium', 'Connect penalty when energy < 0.3');

-- ── sensorium: Fidget and perception ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.fidget.recency_seconds', 300.0, 300.0, 30.0, 1800.0, 'sensorium', 'Only match fidgets from the last N seconds');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.fidget.mismatch_salience', 0.4, 0.4, 0.0, 1.0, 'sensorium', 'Salience for fidget mismatch perception');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sensorium.perception.max_count', 6.0, 6.0, 2.0, 12.0, 'sensorium', 'Maximum perceptions per cycle (focus + background)');

-- ═══ basal_ganglia ═══

-- ── basal_ganglia: Trust priority bonus ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.trust_bonus.stranger', 0.0, 0.0, 0.0, 0.5, 'basal_ganglia', 'Priority bonus: stranger');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.trust_bonus.returner', 0.05, 0.05, 0.0, 0.5, 'basal_ganglia', 'Priority bonus: returner');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.trust_bonus.regular', 0.10, 0.10, 0.0, 0.5, 'basal_ganglia', 'Priority bonus: regular');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.trust_bonus.familiar', 0.15, 0.15, 0.0, 0.5, 'basal_ganglia', 'Priority bonus: familiar');

-- ── basal_ganglia: Priority calculation ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.priority.social_hunger_factor', 0.3, 0.3, 0.0, 1.0, 'basal_ganglia', 'Social drive amplification for visitor actions');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.priority.interest_bonus', 0.1, 0.1, 0.0, 0.5, 'basal_ganglia', 'Bonus for questions/gifts/personal content');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.priority.disengagement_factor', 0.5, 0.5, 0.0, 1.0, 'basal_ganglia', 'Multiplier when absorbed and convo is dull');

-- ── basal_ganglia: Inhibition gating ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.inhibition.strength_threshold', 0.2, 0.2, 0.0, 1.0, 'basal_ganglia', 'Minimum inhibition strength to suppress');

-- ── basal_ganglia: Habit auto-fire ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.habit.strength_threshold', 0.6, 0.6, 0.0, 1.0, 'basal_ganglia', 'Min habit strength for auto-fire');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.habit.cooldown_cycles', 3.0, 3.0, 1.0, 20.0, 'basal_ganglia', 'Cycles between habit re-fires');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('basal_ganglia.habit.open_shop_rest_gate', 0.6, 0.6, 0.0, 1.0, 'basal_ganglia', 'Rest need must be below this to open shop');

-- ═══ output ═══

-- ── output: Drive effects from actions ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.drives.end_engagement_rest_relief', -0.03, -0.03, -0.2, 0.0, 'output', 'Rest need relief from ending engagement');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.drives.failure_valence_penalty', -0.05, -0.05, -0.5, 0.0, 'output', 'Mood penalty per failed action');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.drives.success_bonus_base', 0.02, 0.02, 0.0, 0.2, 'output', 'Base mood bonus per success');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.drives.success_habituation_divisor', 10.0, 10.0, 1.0, 50.0, 'output', 'Habituation divisor for success bonus');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.drives.quiet_cycle_rest_relief', -0.06, -0.06, -1.0, 0.0, 'output', 'Rest need relief per hour on quiet cycles (scaled by elapsed_hours)');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.drives.non_routine_arousal_bump', 0.04, 0.04, 0.0, 0.2, 'output', 'Arousal bump from non-routine actions');

-- ── output: Resonance effects ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.resonance.social_relief', 0.15, 0.15, 0.0, 0.5, 'output', 'Social hunger relief on resonance');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.resonance.valence_boost', 0.1, 0.1, 0.0, 0.5, 'output', 'Valence boost on resonance');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.resonance.curiosity_relief', 0.03, 0.03, 0.0, 0.2, 'output', 'Curiosity relief from engaging conversation');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.resonance.arousal_boost', 0.06, 0.06, 0.0, 0.5, 'output', 'Arousal spike on resonance');

-- ── output: Inhibition formation ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.inhibition.strength_increment', 0.15, 0.15, 0.0, 0.5, 'output', 'Inhibition strength increase on negative signal');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.inhibition.initial_strength', 0.3, 0.3, 0.0, 1.0, 'output', 'New inhibition starting strength');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.inhibition.decay_amount', 0.1, 0.1, 0.0, 0.5, 'output', 'Inhibition weakening on positive signal');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.inhibition.delete_threshold', 0.05, 0.05, 0.0, 0.5, 'output', 'Delete inhibition below this strength');

-- ── output: Habit tracking ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.habit.strength_cap', 0.9, 0.9, 0.5, 1.0, 'output', 'Maximum habit strength');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.habit.decay_rate', 0.01, 0.01, 0.0, 0.1, 'output', 'Habit strength loss per idle hour');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.habit.delete_threshold', 0.05, 0.05, 0.0, 0.5, 'output', 'Delete habit below this strength');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.habit.delta_fast', 0.12, 0.12, 0.01, 0.5, 'output', 'Habit strength increment 0 to 0.4');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.habit.delta_medium', 0.06, 0.06, 0.01, 0.5, 'output', 'Habit strength increment 0.4 to 0.6');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.habit.delta_slow', 0.03, 0.03, 0.01, 0.5, 'output', 'Habit strength increment 0.6+');

-- ── output: Reflection parameters ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.reflection.totem_weight_boost', 0.1, 0.1, 0.0, 0.5, 'output', 'Totem weight increase on content match');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.reflection.new_totem_weight', 0.3, 0.3, 0.0, 1.0, 'output', 'Initial weight for content-linked totem');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.reflection.topic_similarity_threshold', 0.5, 0.5, 0.0, 1.0, 'output', 'Keyword overlap ratio for topic merge');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.reflection.boring_curiosity_drain', -0.02, -0.02, -0.2, 0.0, 'output', 'Diversive curiosity loss from boring content');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.reflection.resolved_curiosity_drain', -0.05, -0.05, -0.2, 0.0, 'output', 'Curiosity loss after resolution');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.reflection.memory_valence_bump', 0.03, 0.03, 0.0, 0.2, 'output', 'Valence boost from memory creation');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('output.reflection.question_arousal_bump', 0.05, 0.05, 0.0, 0.2, 'output', 'Arousal boost from raising question');

-- ═══ sleep ═══

-- ── sleep: Consolidation parameters ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.consolidation.max_reflections', 7.0, 7.0, 1.0, 20.0, 'sleep', 'Max moments to reflect on per sleep');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.consolidation.min_salience', 0.45, 0.45, 0.0, 1.0, 'sleep', 'Min salience for sleep reflection');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.consolidation.max_retries', 3.0, 3.0, 1.0, 10.0, 'sleep', 'Max retries for poison moments');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.consolidation.nap_top_n', 3.0, 3.0, 1.0, 10.0, 'sleep', 'Moments per nap consolidation');

-- ── sleep: Cleanup thresholds ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.cleanup.stale_day_memory_days', 2.0, 2.0, 1.0, 14.0, 'sleep', 'Max age for unprocessed day memory');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.cleanup.dormant_thread_hours', 48.0, 48.0, 12.0, 168.0, 'sleep', 'Hours before thread goes dormant');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.cleanup.archive_thread_days', 7.0, 7.0, 1.0, 30.0, 'sleep', 'Days before dormant thread archived');

-- ── sleep: Morning reset drive values ──
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.morning.social_hunger', 0.5, 0.5, 0.0, 1.0, 'sleep', 'Morning reset: social hunger');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.morning.curiosity', 0.5, 0.5, 0.0, 1.0, 'sleep', 'Morning reset: curiosity');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.morning.expression_need', 0.3, 0.3, 0.0, 1.0, 'sleep', 'Morning reset: expression need');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.morning.rest_need', 0.2, 0.2, 0.0, 1.0, 'sleep', 'Morning reset: rest need');
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description) VALUES
    ('sleep.morning.energy', 1.0, 1.0, 0.0, 1.0, 'sleep', 'Morning reset: energy');
