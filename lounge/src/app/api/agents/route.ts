/**
 * GET /api/agents — List agents. Returns all agents (public); includes
 *   `is_owner` flag when the caller is an authenticated manager.
 * POST /api/agents — Create a new agent (requires auth).
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { createAgentContainer, destroyAgentContainer } from '@/lib/docker-client';
import { getAgentHealth } from '@/lib/agent-client';
import type { CreateAgentRequest } from '@/lib/types';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function GET() {
  const managerId = await getManagerId();

  // Return all agents; tag ownership when a manager is logged in
  const agents = await db.listAllAgents();

  // Enrich with runtime status + ownership flag; strip internal fields
  const enriched = await Promise.all(
    agents.map(async (agent) => ({
      id: agent.id,
      name: agent.name,
      role: agent.role,
      status: (await getAgentHealth(agent.id)) ? 'running' as const : 'stopped' as const,
      is_owner: managerId ? agent.manager_id === managerId : false,
      created_at: agent.created_at,
      updated_at: agent.updated_at,
    }))
  );

  return NextResponse.json({ agents: enriched, authenticated: !!managerId });
}

export async function POST(request: Request) {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  try {
    const body: CreateAgentRequest = await request.json();

    if (!body.openrouter_key?.trim()) {
      return NextResponse.json({ error: 'openrouter_key required' }, { status: 400 });
    }

    // Gateway mode: port=0 (no host port mapping)
    const port = 0;

    // Create agent record
    const agentName = body.name?.trim() || 'Unnamed';
    const agent = await db.createAgent(agentName, managerId, port, body.openrouter_key.trim(), body.role?.trim(), body.bio?.trim());

    // Create initial API key
    const apiKey = await db.createApiKey(agent.id, 'default');

    // Start container (Gateway mode — no host port)
    const result = await createAgentContainer(
      agent.id,
      port,
      apiKey.key,
      body.openrouter_key.trim()
    );

    if (!result.success) {
      // Rollback: destroy container/data (may partially exist) + remove DB records
      await destroyAgentContainer(agent.id, true);
      await db.deleteAgent(agent.id);
      return NextResponse.json({
        error: 'container failed to start',
        output: result.output,
      }, { status: 502 });
    }

    // Sync API keys to agent config dir so the live agent can authenticate
    await db.syncApiKeysToAgent(agent.id);

    return NextResponse.json({
      agent,
      api_key: apiKey,
      container: { success: result.success, output: result.output },
    }, { status: 201 });
  } catch {
    return NextResponse.json({ error: 'failed to create agent' }, { status: 500 });
  }
}
