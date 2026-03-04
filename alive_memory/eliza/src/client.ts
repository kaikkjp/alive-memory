/**
 * REST API client for the alive-memory server.
 */

import type {
  BackstoryRequest,
  CognitiveStateResponse,
  ConsolidateRequest,
  DayMomentResponse,
  DriveStateResponse,
  DriveUpdateRequest,
  HealthResponse,
  IntakeRequest,
  RecallContextResponse,
  RecallRequest,
  SelfModelResponse,
  SleepReportResponse,
} from "./types";

export interface AliveClientConfig {
  /** Base URL of the alive-memory server (e.g. "http://localhost:8100") */
  baseUrl: string;
  /** Optional bearer token for authentication */
  apiKey?: string;
}

export class AliveMemoryClient {
  private baseUrl: string;
  private headers: Record<string, string>;

  constructor(config: AliveClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.headers = { "Content-Type": "application/json" };
    if (config.apiKey) {
      this.headers["Authorization"] = `Bearer ${config.apiKey}`;
    }
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: this.headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(
        `alive-memory API error: ${resp.status} ${resp.statusText} — ${text}`,
      );
    }

    return resp.json() as Promise<T>;
  }

  async health(): Promise<HealthResponse> {
    return this.request("GET", "/health");
  }

  /** Record an event. Returns a DayMoment if salient enough, null otherwise. */
  async intake(req: IntakeRequest): Promise<DayMomentResponse | null> {
    return this.request("POST", "/intake", req);
  }

  /** Retrieve context from hot memory (Tier 2 markdown grep). */
  async recall(req: RecallRequest): Promise<RecallContextResponse> {
    return this.request("POST", "/recall", req);
  }

  /** Run consolidation (sleep). */
  async consolidate(
    req: ConsolidateRequest = {},
  ): Promise<SleepReportResponse> {
    return this.request("POST", "/consolidate", req);
  }

  async getState(): Promise<CognitiveStateResponse> {
    return this.request("GET", "/state");
  }

  async getIdentity(): Promise<SelfModelResponse> {
    return this.request("GET", "/identity");
  }

  async updateDrive(
    name: string,
    req: DriveUpdateRequest,
  ): Promise<DriveStateResponse> {
    return this.request("POST", `/drives/${name}`, req);
  }

  async injectBackstory(req: BackstoryRequest): Promise<DayMomentResponse> {
    return this.request("POST", "/backstory", req);
  }
}
