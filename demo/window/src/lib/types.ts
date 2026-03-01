/** TypeScript types matching backend WebSocket/REST payloads. */

// ─── Fragment Types ───

export type FragmentType =
  | 'journal'
  | 'thought'
  | 'action'
  | 'speech'
  | 'sleep_reflection'
  | 'thread_update'
  | 'response'
  | 'visitor_speech';

export interface Fragment {
  id: string;
  content: string;
  type: FragmentType;
  timestamp: string;
}

// ─── Chat Messages ───

export interface ChatMessage {
  id: string;
  content: string;
  sender: 'visitor' | 'shopkeeper';
  timestamp: string;
}

// ─── Scene Types ───

export type SpriteState =
  | 'surprised'
  | 'tired'
  | 'engaged'
  | 'curious'
  | 'focused'
  | 'thinking'
  | 'smiling';

export type TimeOfDay =
  | 'morning'
  | 'afternoon'
  | 'evening'
  | 'night';

export type ShopkeeperStatus = 'awake' | 'sleeping' | 'resting';

// ─── Scene Layers ───

export interface SceneLayers {
  background: string;
  shop: string;
  character: string;
}

// ─── Window State ───

export interface ThreadInfo {
  id: string;
  title: string;
  status: string;
  thread_type?: string;
  tags?: string[];
  touch_count?: number;
  last_touched?: string | null;
}

export interface WindowState {
  threads: ThreadInfo[];
  weather_diegetic: string;
  time_label: string;
  status: ShopkeeperStatus;
  visitor_present: boolean;
  sprite_state: SpriteState;
  time_of_day: TimeOfDay;
}

// ─── Text Entry (legacy compat) ───

export interface TextEntry {
  content: string;
  type: FragmentType;
  timestamp: string;
}

// ─── WebSocket Messages: Server → Client ───

export interface SceneUpdateMessage {
  type: 'scene_update';
  layers: SceneLayers;
  text: {
    current_thought?: string;
    activity_label?: string;
    recent_entries?: TextEntry[];
  };
  state: WindowState;
  chat_history?: ChatHistoryEntry[];
  timestamp: string;
}

/** Chat history entry — sent in initial scene_update payload on connect. */
export interface ChatHistoryEntry {
  type: 'chat_message' | 'chat_response';
  sender?: string;
  sender_type?: 'visitor' | 'shopkeeper';
  content: string;
  expression?: string;
  timestamp: string;
}

// ─── WebSocket Messages: Server → Client (discriminated union) ───

export type ServerMessage =
  | SceneUpdateMessage
  | { type: 'text_fragment'; content: string; fragment_type: FragmentType; timestamp: string }
  | { type: 'expression_change'; expression: string; sprite_url: string }
  | { type: 'status'; status: ShopkeeperStatus; message: string }
  | { type: 'chat_response'; content: string; expression: string; timestamp: string }
  | { type: 'token_result'; valid: boolean; display_name?: string; error?: string }
  | { type: 'chat_ack'; timestamp: string }
  | { type: 'chat_error'; message: string }
  | { type: 'chat_message'; sender: string; sender_type: 'visitor' | 'shopkeeper'; content: string; timestamp: string }
  | { type: 'visitor_presence'; visitors: { display_name: string; visitor_id: string }[]; visitor_count: number; timestamp: string };

// ═══════════════════════════════════════════════
// Dashboard types (unchanged — for /dashboard)
// ═══════════════════════════════════════════════

export interface ActionCapabilityView {
  action: string;
  enabled: boolean;
  ready: boolean;
  cooling_until: string | null;
}

export interface BodyPanelData {
  capabilities: ActionCapabilityView[];
  actions_today: { type: string; count: number; total_energy: number }[];
}

export interface BudgetData {
  budget: number;
  spent: number;
  remaining: number;
}

export interface HabitView {
  action: string;
  trigger_context: string;
  strength: number;
  last_fired: string;
  fire_count: number;
}

export interface InhibitionView {
  action: string;
  context: string;
  strength: number;
  trigger_count: number;
}

export interface SuppressionView {
  action: string;
  impulse: number;
  reason: string;
  timestamp: string;
}

export interface BehavioralPanelData {
  habits: HabitView[];
  inhibitions: InhibitionView[];
  suppressions: SuppressionView[];
  habit_skips_today: number;
}

export interface ContentPoolTypeBreakdown {
  source_type: string;
  count: number;
}

export interface ContentPoolRecentItem {
  title: string;
  source_type: string;
  added_at: string;
}

export interface ContentPoolData {
  total: number;
  by_type: ContentPoolTypeBreakdown[];
  recent: ContentPoolRecentItem[];
  oldest_age_hours: number | null;
}

export interface FeedPanelData {
  status: 'running' | 'paused' | 'error';
  queue_depth: number;
  last_success_ts: string | null;
  failed_24h: number;
  last_error: string | null;
  rate_24h: number;
}

export interface ConsumptionHistoryEntry {
  id: string;
  title: string;
  source_type: string;
  consumed_at: string;
  outcomes: string[];
}

export interface ConsumptionHistoryData {
  entries: ConsumptionHistoryEntry[];
}

export interface ParameterView {
  key: string;
  value: number;
  default_value: number;
  min_bound: number | null;
  max_bound: number | null;
  category: string;
  description: string;
  modified_by: string;
  modified_at: string;
  created_at: string;
}

export interface ParameterModification {
  id: number;
  param_key: string;
  old_value: number;
  new_value: number;
  modified_by: string;
  reason: string | null;
  ts: string;
}

export interface ParametersPanelData {
  categories: Record<string, ParameterView[]>;
  recent_modifications: ParameterModification[];
  total_count: number;
}

// ─── Dashboard: Actions Panel (TASK-056) ───

export interface DynamicAction {
  action_name: string;
  alias_for: string | null;
  body_state: string | null;
  status: 'pending' | 'alias' | 'body_state' | 'promoted' | 'rejected';
  attempt_count: number;
  promote_threshold: number;
  first_seen: string;
  last_seen: string;
  resolved_by: string | null;
  notes: string | null;
}

export interface ActionsPanelData {
  actions: DynamicAction[];
  stats: {
    total: number;
    by_status: Record<string, number>;
    top_pending: Array<{ action_name: string; attempt_count: number }>;
  };
}

// ─── Dashboard: X Drafts Panel (TASK-057) ───


export interface XDraft {
  id: string;
  draft_text: string;
  status: 'pending' | 'approved' | 'rejected' | 'posted' | 'failed';
  created_at: string;
  reviewed_at?: string;
  posted_at?: string;
  x_post_id?: string;
  rejection_reason?: string;
  error_message?: string;
}

export interface XDraftsData {
  drafts: XDraft[];
  pending_count: number;
}

// ─── Dashboard: External Actions (TASK-069) ───

export interface ExternalRateLimitStatus {
  action: string;
  hourly_used: number;
  hourly_limit: number;
  daily_used: number;
  daily_limit: number;
  cooldown_remaining: number;
  cooldown_seconds: number;
}

export interface ChannelStatus {
  channel: string;
  enabled: boolean;
  disabled_at: string | null;
  disabled_by: string | null;
}

export interface ExternalActionLogEntry {
  action: string;
  timestamp: string;
  success: boolean;
  channel: string | null;
  error: string | null;
}

export interface ExternalActionsData {
  rate_limits: ExternalRateLimitStatus[];
  channels: ChannelStatus[];
  recent_log: ExternalActionLogEntry[];
}

// ─── Dashboard: Meta-Controller (TASK-090/096) ───

export interface MetaControllerTarget {
  min: number | null;
  max: number | null;
  metric: string;
  current: number | null;
  status: 'ok' | 'low' | 'high' | 'unknown';
  last_updated: string | null;
}

export interface MetaControllerConfig {
  evaluation_window: number;
  cooldown_cycles: number;
  max_adjustments_per_sleep: number;
}

export interface MetaControllerData {
  enabled: boolean;
  targets: Record<string, MetaControllerTarget>;
  recent_adjustments: MetaExperiment[];
  pending_count: number;
  config: MetaControllerConfig;
}

// ─── Dashboard: Experiment History (TASK-091/096) ───

export interface MetaExperiment {
  id: number;
  cycle_at_change: number;
  param_name: string;
  old_value: number;
  new_value: number;
  reason: string | null;
  target_metric: string | null;
  metric_value_at_change: number | null;
  metric_value_after: number | null;
  outcome: 'pending' | 'improved' | 'degraded' | 'neutral' | 'reverted' | string;
  evaluation_cycle: number | null;
  side_effects: Array<Record<string, unknown>> | null;
  confidence_at_change: number | null;
  reverted_at_cycle: number | null;
  created_at: string;
}

export interface MetaConfidence {
  param_name: string;
  target_metric: string;
  attempts: number;
  improved: number;
  degraded: number;
  neutral: number;
  confidence: number;
  avg_effect_size: number | null;
  last_updated_cycle: number | null;
}

export interface ExperimentHistoryData {
  experiments: MetaExperiment[];
  confidence: MetaConfidence[];
}

// ─── Dashboard: Liveness Metrics (TASK-071/096) ───

export interface MetricResult {
  name: string;
  value: number;
  details: Record<string, unknown>;
  display: string;
}

export interface MetricSnapshot {
  timestamp: string;
  period: string;
  metrics: MetricResult[];
}

export interface MetricTrendPoint {
  timestamp: string;
  value: number;
}

export interface MetricsData {
  snapshot: MetricSnapshot;
  trends: Record<string, MetricTrendPoint[]>;
}

// ─── Dashboard: Drift Detection (TASK-062) ───

export interface DriftMetrics {
  action_frequency: number;
  drive_response: number;
  conversation_style: number;
  sleep_wake_rhythm: number;
}

export interface DriftData {
  composite: number;
  metrics: DriftMetrics;
  level: 'none' | 'notable' | 'significant';
  summary: string | null;
  baseline_cycles: number;
  baseline_mature: boolean;
}
