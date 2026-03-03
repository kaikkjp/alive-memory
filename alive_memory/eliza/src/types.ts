/**
 * TypeScript types matching the alive-memory REST API models.
 */

export interface IntakeRequest {
  event_type: string;
  content: string;
  metadata?: Record<string, unknown>;
  timestamp?: string;
}

export interface RecallRequest {
  query: string;
  limit?: number;
  min_strength?: number;
}

export interface ConsolidateRequest {
  whispers?: Record<string, unknown>[];
  depth?: "full" | "nap";
}

export interface DriveUpdateRequest {
  delta: number;
}

export interface BackstoryRequest {
  content: string;
  title?: string;
}

export interface MemoryResponse {
  id: string;
  content: string;
  memory_type: string;
  strength: number;
  valence: number;
  formed_at: string;
  last_recalled: string | null;
  recall_count: number;
  source_event: string | null;
  drive_coupling: Record<string, number>;
  metadata: Record<string, unknown>;
}

export interface MoodResponse {
  valence: number;
  arousal: number;
  word: string;
}

export interface DriveStateResponse {
  curiosity: number;
  social: number;
  expression: number;
  rest: number;
}

export interface CognitiveStateResponse {
  mood: MoodResponse;
  energy: number;
  drives: DriveStateResponse;
  cycle_count: number;
  last_sleep: string | null;
  memories_total: number;
}

export interface SelfModelResponse {
  traits: Record<string, number>;
  behavioral_summary: string;
  drift_history: Record<string, unknown>[];
  version: number;
  snapshot_at: string | null;
}

export interface ConsolidationReportResponse {
  memories_strengthened: number;
  memories_weakened: number;
  memories_pruned: number;
  memories_merged: number;
  dreams: string[];
  reflections: string[];
  identity_drift: Record<string, unknown> | null;
  duration_ms: number;
}

export interface HealthResponse {
  status: string;
  version: string;
}
