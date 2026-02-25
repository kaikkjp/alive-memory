/**
 * GET /api/agents/:id/status — Proxy to agent's /api/public-state.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { getAgentStatus, getAgentHealth } from '@/lib/agent-client';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const { id } = await params;
  const owns = await db.agentBelongsToManager(id, managerId);
  if (!owns) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  const agent = await db.getAgent(id);
  if (!agent) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  // Check basic health first
  const healthy = await getAgentHealth(agent.port);
  if (!healthy) {
    return NextResponse.json({
      status: 'offline',
      port: agent.port,
    });
  }

  // Try to get full status (needs an API key)
  const keys = await db.listApiKeys(id);
  if (keys.length > 0) {
    const status = await getAgentStatus(agent.port, keys[0].key);
    if (status) {
      return NextResponse.json(status);
    }
  }

  // Fallback: container is running but no detailed status
  return NextResponse.json({
    status: 'active',
    port: agent.port,
  });
}
