/**
 * TASK-095 Phase 5: Core types for the manager portal.
 */

export interface Manager {
  id: string;
  name: string;
  created_at: string;
}

export interface Agent {
  id: string;
  name: string;
  role?: string;
  manager_id: string;
  port: number;
  status: 'running' | 'stopped' | 'error';
  created_at: string;
  updated_at: string;
  cycle_count?: number;
  is_owner?: boolean;
}

export interface AgentConfig {
  identity_compact: string;
  voice_rules: string[];
  communication_style: string;
  language: string;
  greeting: string;
  boundaries: string;
}

export interface ApiKey {
  id: string;
  agent_id: string;
  key: string;
  name: string;
  rate_limit: number;
  created_at: string;
}

export interface AgentStatus {
  status: 'active' | 'inactive';
  mood: { valence: number; arousal: number };
  energy: number;
  engaged: boolean;
  timestamp: string;
}

export interface CreateAgentRequest {
  name: string;
  openrouter_key: string;
  role?: string;
  bio?: string;
}

export interface CreateApiKeyRequest {
  name: string;
  rate_limit?: number;
}

// ── TASK-095 v2: Soul Features ──

export interface DriveState {
  value: number;
  label: string;
  equilibrium?: number;
}

export interface AgentDrives {
  energy: number;
  curiosity: DriveState;
  social_hunger: DriveState;
  expression_need: DriveState;
  rest_need: DriveState;
  mood_valence: number;
  mood_arousal: number;
}

export interface ExpandedAgentStatus extends AgentStatus {
  drives?: AgentDrives;
  recent_actions?: Array<{
    action: string;
    timestamp: string;
    content?: string;
  }>;
  mood_word?: string;
  state_description?: string;
}

export interface Whisper {
  id: number;
  param_path: string;
  old_value?: string;
  new_value: string;
  created_at: string;
  processed_at?: string;
  dream_text?: string;
}

export interface CreateWhisperRequest {
  param_path: string;
  new_value: string;
}

export interface Memory {
  source_id: string;
  text_content: string;
  origin: 'organic' | 'manager_injected';
  ts_iso?: string;
  source_type?: string;
}

export interface InjectMemoryRequest {
  text: string;
  title?: string;
}

export interface ActionCapability {
  name: string;
  enabled: boolean;
  description?: string;
  energy_cost?: number;
}

// ── TASK-095 v3.1 Batch 2: Portal Backend ──

export interface OrganismParams {
  evolution_speed: number;
  complexity: number;
  stroke_alpha: number;
  color_temp: number;
  bg_darkness: number;
  amplitude: number;
  phase_offsets: [number, number, number];
  dream_flare: boolean;
  thinking_boost: boolean;
}

export interface InnerVoiceEntry {
  text: string;
  timestamp: string;
  cycle_id?: string;
  cycle_type?: string;
}

export interface FeedDrop {
  id: number;
  title: string;
  content: string;
  source_type: string;
  status: string;
  added_at: string;
  consumed_at?: string;
  consumption_output?: string;
}

export interface FeedStream {
  id: number;
  url: string;
  label?: string;
  active: boolean;
  poll_interval_minutes: number;
  last_fetched_at?: string;
  items_fetched: number;
  created_at: string;
}

export interface ChannelStatus {
  channel: string;
  enabled: boolean;
  last_activity?: string;
  message_count?: number;
}

export interface ExpandedLoungeState {
  status: 'active' | 'inactive' | 'offline';
  drives?: {
    curiosity: number;
    social_hunger: number;
    expression_need: number;
  };
  mood?: { valence: number; arousal: number };
  energy?: number;
  engaged?: boolean;
  inner_voice?: string | null;
  organism_params?: OrganismParams;
  engagement_state?: string;
  current_action?: string;
  is_sleeping?: boolean;
  cycle_count?: number;
  timestamp?: string;
}

// ── TASK-095 v3.1 Batch 4: Lounge Frontend ──

export interface AgentStreamState {
  drives: {
    curiosity: number;
    social_hunger: number;
    expression_need: number;
    rest_need: number;
    energy: number;
    mood_valence: number;
    mood_arousal: number;
  } | null;
  mood: { valence: number; arousal: number } | null;
  energy: number;
  engagement_state: string;
  is_sleeping: boolean;
  is_dreaming: boolean;
  cycle_count: number;
  inner_voice: InnerVoiceEntry[];
  recent_actions: Array<{ action: string; timestamp: string; content?: string }>;
  current_action: string | null;
  status: 'connected' | 'reconnecting' | 'offline' | 'error';
  lastUpdate: string | null;
}

export interface ChatMessage {
  role: 'user' | 'agent' | 'system';
  text: string;
  timestamp: string;
}

export interface CapabilityWithUsage extends ActionCapability {
  usage_count?: number;
  source?: 'builtin' | 'mcp';
}

// TASK-107: Dynamic actions
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

export interface DynamicActionsData {
  actions: DynamicAction[];
  stats: {
    total: number;
    by_status: Record<string, number>;
    top_pending: Array<{ action_name: string; attempt_count: number }>;
  };
}

// TASK-095 v3.1 Batch 3: MCP types
export interface McpToolInfo {
  name: string;
  description: string;
  enabled: boolean;
  usage_count: number;
  action_suffix: string;
}

export interface McpServer {
  id: number;
  name: string;
  url: string;
  enabled: boolean;
  tools: McpToolInfo[];
  connected_at: string;
}

// TASK-108: Full memory view types
export interface Thread {
  id: string;
  title: string;
  status: string;
  thread_type: string;
  tags: string[];
  touch_count: number;
  last_touched: string | null;
}

export interface JournalEntry {
  id: string;
  content: string;
  mood: string | null;
  day_alive: number | null;
  tags: string[];
  created_at: string | null;
}

export interface Totem {
  id: string;
  entity: string;
  weight: number;
  context: string | null;
  category: string | null;
  visitor_id: string | null;
  first_seen: string | null;
  last_referenced: string | null;
}

export interface DayMemory {
  id: string;
  summary: string;
  salience: number;
  moment_type: string;
  visitor_id: string | null;
  ts: string;
}

export interface CollectionItem {
  id: string;
  title: string;
  item_type: string;
  location: string;
  origin: string;
  her_feeling: string | null;
  created_at: string | null;
}

export interface DailySummary {
  id: string;
  day_number: number | null;
  date: string | null;
  emotional_arc: string | null;
  moment_count: number;
  moment_ids: string[];
  journal_entry_ids: string[];
}
