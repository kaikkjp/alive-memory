/**
 * TypeScript types matching the alive-memory REST API models.
 *
 * These types correspond to the Pydantic response models in
 * alive_memory/server/models.py. Keep in sync with the Python source.
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

/** Response from POST /intake and POST /backstory (Tier 1 day moment). */
export interface DayMomentResponse {
  id: string;
  content: string;
  event_type: string;
  salience: number;
  valence: number;
  drive_snapshot: Record<string, number>;
  timestamp: string;
  metadata: Record<string, unknown>;
}

/** Response from POST /recall (Tier 2 hot memory grep results). */
export interface RecallContextResponse {
  journal_entries: string[];
  visitor_notes: string[];
  self_knowledge: string[];
  reflections: string[];
  thread_context: string[];
  query: string;
  total_hits: number;
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

/** Response from POST /consolidate (sleep report). */
export interface SleepReportResponse {
  moments_processed: number;
  journal_entries_written: number;
  reflections_written: number;
  cold_embeddings_added: number;
  cold_echoes_found: number;
  dreams: string[];
  reflections: string[];
  identity_drift: Record<string, unknown> | null;
  duration_ms: number;
  depth: string;
}

export interface HealthResponse {
  status: string;
  version: string;
}
