/**
 * TASK-095 Phase 5: HTTP client for talking to agent containers.
 *
 * Each agent exposes HTTP on its assigned port (localhost only).
 * This client proxies requests from the portal backend to agents.
 */

import type { AgentStatus } from './types';

const AGENT_TIMEOUT = 10_000; // 10s

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
