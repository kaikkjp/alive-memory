/**
 * TASK-095 Phase 5: HTTP client for talking to agent containers.
 *
 * Each agent exposes HTTP on its assigned port (localhost only).
 * This client proxies requests from the portal backend to agents.
 */

import type { AgentStatus } from './types';

const AGENT_TIMEOUT = 10_000; // 10s
const DASHBOARD_TIMEOUT = 15_000; // 15s for dashboard endpoints

export async function getAgentHealth(port: number): Promise<boolean> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/health`, {
      signal: AbortSignal.timeout(5_000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function getAgentStatus(port: number, apiKey: string): Promise<AgentStatus | null> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/public-state`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(AGENT_TIMEOUT),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Generic dashboard GET — proxy to agent's /api/dashboard/* endpoints.
 * Uses first API key for auth (dashboard auth uses same Bearer token).
 */
export async function dashboardGet(
  port: number,
  apiKey: string,
  path: string
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/dashboard/${path}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(DASHBOARD_TIMEOUT),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Generic dashboard POST — proxy to agent's /api/dashboard/* endpoints.
 */
export async function dashboardPost(
  port: number,
  apiKey: string,
  path: string,
  body?: Record<string, unknown>
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/dashboard/${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(DASHBOARD_TIMEOUT),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Generic dashboard DELETE — proxy to agent's /api/dashboard/* endpoints.
 */
export async function dashboardDelete(
  port: number,
  apiKey: string,
  path: string
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/dashboard/${path}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(DASHBOARD_TIMEOUT),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function chatWithAgent(
  port: number,
  apiKey: string,
  message: string,
  visitorId?: string
): Promise<Record<string, unknown> | null> {
  try {
    const body: Record<string, string> = { message };
    if (visitorId) body.visitor_id = visitorId;

    const res = await fetch(`http://127.0.0.1:${port}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(35_000), // 30s agent timeout + buffer
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}
