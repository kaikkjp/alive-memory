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
