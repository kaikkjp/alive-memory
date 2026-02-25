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
  manager_id: string;
  port: number;
  status: 'running' | 'stopped' | 'error';
  created_at: string;
  updated_at: string;
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
