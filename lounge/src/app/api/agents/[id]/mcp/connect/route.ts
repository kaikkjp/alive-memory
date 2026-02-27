/**
 * TASK-095 v3.1 Batch 3: MCP server connect.
 *
 * POST /api/agents/:id/mcp/connect — Connect to an MCP server
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { getAgentHealth, dashboardFetchRaw } from '@/lib/agent-client';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function POST(
  request: Request,
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

  const body = await request.json();
  if (!body.url) {
    return NextResponse.json({ error: 'url required' }, { status: 400 });
  }

  const healthy = await getAgentHealth(agent.port);
  if (!healthy) {
    return NextResponse.json({ error: 'agent offline' }, { status: 502 });
  }

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no api key' }, { status: 500 });
  }

  const { data, status } = await dashboardFetchRaw(
    agent.port, keys[0].key, 'POST', 'mcp/connect',
    { url: body.url, name: body.name }
  );

  if (status === 0) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }
  if (status >= 400) {
    return NextResponse.json({ error: data ?? 'engine error' }, { status });
  }

  return NextResponse.json(data);
}
