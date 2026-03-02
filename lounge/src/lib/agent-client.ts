/**
 * TASK-119: Gateway-based agent client.
 *
 * All agent communication routes through the Gateway process
 * (HTTP :8000) instead of per-agent host ports. The Gateway
 * forwards requests as RPC-over-WS to the connected agent.
 *
 * Auth model:
 *   Lounge → Gateway: X-Gateway-Token header (admin shared secret)
 *   Gateway → Agent:  Authorization header passes through transparently
 *
 * URL pattern: http://<gateway>/agents/<agentId>/<agent-path>
 */

import type { AgentStatus } from './types';

const AGENT_TIMEOUT = 10_000; // 10s
const DASHBOARD_TIMEOUT = 15_000; // 15s for dashboard endpoints

// Gateway connection config — set via env vars on VPS
const GATEWAY_URL = process.env.GATEWAY_URL || 'http://127.0.0.1:8000';
const GATEWAY_ADMIN_TOKEN = process.env.GATEWAY_ADMIN_TOKEN || '';

/** Build a Gateway-proxied URL for an agent endpoint. */
function agentUrl(agentId: string, path: string): string {
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${GATEWAY_URL}/agents/${agentId}${clean}`;
}

/** Standard headers for Gateway requests. */
function gatewayHeaders(apiKey?: string): Record<string, string> {
  const hdrs: Record<string, string> = {
    'X-Gateway-Token': GATEWAY_ADMIN_TOKEN,
  };
  if (apiKey) hdrs['Authorization'] = `Bearer ${apiKey}`;
  return hdrs;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export async function getAgentHealth(agentId: string): Promise<boolean> {
  try {
    const res = await fetch(`${GATEWAY_URL}/agents/${agentId}/health`, {
      headers: { 'X-Gateway-Token': GATEWAY_ADMIN_TOKEN },
      signal: AbortSignal.timeout(5_000),
    });
    if (!res.ok) return false;
    const data = await res.json();
    return data.status !== 'unreachable';
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Public state
// ---------------------------------------------------------------------------

export async function getAgentStatus(agentId: string, apiKey: string): Promise<AgentStatus | null> {
  try {
    const res = await fetch(agentUrl(agentId, '/api/public-state'), {
      headers: gatewayHeaders(apiKey),
      signal: AbortSignal.timeout(AGENT_TIMEOUT),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Dashboard helpers (GET / POST / PATCH / DELETE)
// ---------------------------------------------------------------------------

export async function dashboardGet(
  agentId: string,
  apiKey: string,
  path: string
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(agentUrl(agentId, `/api/dashboard/${path}`), {
      headers: gatewayHeaders(apiKey),
      signal: AbortSignal.timeout(DASHBOARD_TIMEOUT),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function dashboardPost(
  agentId: string,
  apiKey: string,
  path: string,
  body?: Record<string, unknown>
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(agentUrl(agentId, `/api/dashboard/${path}`), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...gatewayHeaders(apiKey),
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

export async function dashboardPatch(
  agentId: string,
  apiKey: string,
  path: string,
  body?: Record<string, unknown>
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(agentUrl(agentId, `/api/dashboard/${path}`), {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...gatewayHeaders(apiKey),
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

export async function dashboardDelete(
  agentId: string,
  apiKey: string,
  path: string
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(agentUrl(agentId, `/api/dashboard/${path}`), {
      method: 'DELETE',
      headers: gatewayHeaders(apiKey),
      signal: AbortSignal.timeout(DASHBOARD_TIMEOUT),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Raw dashboard fetch (preserves status codes)
// ---------------------------------------------------------------------------

type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';
export interface DashboardRawResult {
  data: unknown;
  status: number; // 0 = network/timeout error
}

export async function dashboardFetchRaw(
  agentId: string,
  apiKey: string,
  method: HttpMethod,
  path: string,
  body?: Record<string, unknown>
): Promise<DashboardRawResult> {
  try {
    const hdrs: Record<string, string> = gatewayHeaders(apiKey);
    if (body) hdrs['Content-Type'] = 'application/json';
    const res = await fetch(agentUrl(agentId, `/api/dashboard/${path}`), {
      method,
      headers: hdrs,
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(DASHBOARD_TIMEOUT),
    });
    if (!res.ok) return { data: null, status: res.status };
    const text = await res.text();
    if (!text) return { data: null, status: res.status };
    try {
      return { data: JSON.parse(text), status: res.status };
    } catch {
      return { data: null, status: res.status };
    }
  } catch {
    return { data: null, status: 0 };
  }
}

// ---------------------------------------------------------------------------
// Chat / conversation
// ---------------------------------------------------------------------------

export async function getConversationHistory(
  agentId: string,
  apiKey: string,
  visitorId: string,
  limit: number = 50
): Promise<{ messages: { role: string; text: string; ts: string }[]; visitor_id: string } | null> {
  try {
    const res = await fetch(agentUrl(agentId, '/api/conversation-history'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...gatewayHeaders(apiKey),
      },
      body: JSON.stringify({ visitor_id: visitorId, limit }),
      signal: AbortSignal.timeout(AGENT_TIMEOUT),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function chatWithAgent(
  agentId: string,
  apiKey: string,
  message: string,
  visitorId?: string,
  source?: string
): Promise<Record<string, unknown> | null> {
  try {
    const body: Record<string, string> = { message };
    if (visitorId) body.visitor_id = visitorId;
    if (source) body.source = source;

    const res = await fetch(agentUrl(agentId, '/api/chat'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...gatewayHeaders(apiKey),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(35_000),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Manager channel — bypasses engagement system.
 * Uses /api/manager-message instead of /api/chat.
 */
export async function managerMessage(
  agentId: string,
  apiKey: string,
  message: string,
  visitorId?: string
): Promise<Record<string, unknown> | null> {
  try {
    const body: Record<string, string> = { message };
    if (visitorId) body.visitor_id = visitorId;

    const res = await fetch(agentUrl(agentId, '/api/manager-message'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...gatewayHeaders(apiKey),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(35_000),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Gateway URL helper (for SSE stream route to fetch directly)
// ---------------------------------------------------------------------------

/** Build a direct Gateway URL for agent state polling. */
export function agentDashboardUrl(agentId: string, path: string): string {
  return agentUrl(agentId, `/api/dashboard/${path}`);
}

/** Return headers needed for Gateway requests. */
export function getGatewayHeaders(apiKey: string): Record<string, string> {
  return gatewayHeaders(apiKey);
}
