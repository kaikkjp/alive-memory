/** TypeScript types matching backend WebSocket/REST payloads. */

export interface SceneLayers {
  background: string;
  shop: string;
  items: ShelfItem[];
  character: string;
  character_position: Position;
  foreground: string[];
  weather: string;
  scene_id: string;
}

export interface ShelfItem {
  sprite: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Position {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TextEntry {
  content: string;
  type: FragmentType;
  timestamp: string;
}

export type FragmentType =
  | 'journal'
  | 'thought'
  | 'thread_update'
  | 'response'
  | 'visitor_speech';

export interface ThreadInfo {
  id: string;
  title: string;
  status: string;
  thread_type?: string;
  tags?: string[];
  touch_count?: number;
  last_touched?: string | null;
}

// ─── Scene Compositor Types ───

export type SpriteState =
  | 'surprised'
  | 'tired'
  | 'engaged'
  | 'curious'
  | 'focused'
  | 'thinking';

export type TimeOfDay =
  | 'morning'
  | 'afternoon'
  | 'evening'
  | 'night';

export interface WindowState {
  threads: ThreadInfo[];
  weather_diegetic: string;
  time_label: string;
  status: 'awake' | 'sleeping' | 'resting';
  visitor_present: boolean;
  sprite_state: SpriteState;
  time_of_day: TimeOfDay;
}

// ─── WebSocket Messages ───

export interface SceneUpdateMessage {
  type: 'scene_update';
  layers: SceneLayers;
  text: {
    current_thought?: string;
    activity_label?: string;
    recent_entries?: TextEntry[];
  };
  state: WindowState;
  timestamp: string;
}

export interface TextFragmentMessage {
  type: 'text_fragment';
  content: string;
  fragment_type: FragmentType;
  timestamp: string;
}

export interface ItemAddedMessage {
  type: 'item_added';
  item: ShelfItem & { description?: string };
  timestamp: string;
}

export interface StatusMessage {
  type: 'status';
  status: 'awake' | 'sleeping' | 'resting';
  message: string;
}

export interface ChatErrorMessage {
  type: 'chat_error';
  message: string;
}

export type ServerMessage =
  | SceneUpdateMessage
  | TextFragmentMessage
  | ItemAddedMessage
  | StatusMessage
  | ChatErrorMessage;

// ─── Client → Server ───

export interface VisitorMessage {
  type: 'visitor_message';
  text: string;
  token: string;
}

export interface VisitorDisconnect {
  type: 'visitor_disconnect';
  token: string;
}

// ─── Aggregated client state ───

export interface ShopkeeperState {
  layers: SceneLayers | null;
  textEntries: TextEntry[];
  windowState: WindowState | null;
  currentThought: string;
  activityLabel: string;
  connected: boolean;
}

// ─── Dashboard: Body Panel ───

export interface ActionCapabilityView {
  action: string;
  enabled: boolean;
  ready: boolean;
  cooling_until: string | null;
  energy_cost: number;
}

export interface BodyPanelData {
  capabilities: ActionCapabilityView[];
  actions_today: { type: string; count: number; total_energy: number }[];
}

// ─── Dashboard: Budget ───

export interface BudgetData {
  budget: number;
  spent: number;
  remaining: number;
}

// ─── Dashboard: Behavioral Panel ───

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

// ─── Dashboard: Content Pool Panel ───

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

// ─── Dashboard: Feed Panel ───

export interface FeedPanelData {
  status: 'running' | 'paused' | 'error';
  queue_depth: number;
  last_success_ts: string | null;
  failed_24h: number;
  last_error: string | null;
  rate_24h: number;
}

// ─── Dashboard: Consumption History Panel ───

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
