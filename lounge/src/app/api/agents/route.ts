/**
 * GET /api/agents — List all agents for the authenticated manager.
 * POST /api/agents — Create a new agent.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { isContainerRunning } from '@/lib/docker-client';
import { createAgentContainer } from '@/lib/docker-client';
import type { CreateAgentRequest } from '@/lib/types';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function GET() {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const agents = await db.listAgents(managerId);

  // Enrich with runtime status
  const enriched = await Promise.all(
    agents.map(async (agent) => ({
      ...agent,
      status: (await isContainerRunning(agent.id)) ? 'running' as const : 'stopped' as const,
    }))
  );

  return NextResponse.json({ agents: enriched });
}

export async function POST(request: Request) {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  try {
    const body: CreateAgentRequest = await request.json();

    if (!body.name?.trim()) {
      return NextResponse.json({ error: 'name required' }, { status: 400 });
    }
    if (!body.openrouter_key?.trim()) {
      return NextResponse.json({ error: 'openrouter_key required' }, { status: 400 });
    }

    // Allocate port
    const port = await db.getNextPort();

    // Create agent record
    const agent = await db.createAgent(body.name.trim(), managerId, port, body.openrouter_key.trim());

    // Create initial API key
    const apiKey = await db.createApiKey(agent.id, 'default');

    // Start container
    const result = await createAgentContainer(
      agent.id,
      port,
      apiKey.key,
      body.openrouter_key.trim()
    );

    if (!result.success) {
      // Rollback: remove DB records since container failed
      await db.deleteAgent(agent.id);
      return NextResponse.json({
        error: 'container failed to start',
        output: result.output,
      }, { status: 502 });
    }

    return NextResponse.json({
      agent,
      api_key: apiKey,
      container: { success: result.success, output: result.output },
    }, { status: 201 });
  } catch {
    return NextResponse.json({ error: 'failed to create agent' }, { status: 500 });
  }
}
