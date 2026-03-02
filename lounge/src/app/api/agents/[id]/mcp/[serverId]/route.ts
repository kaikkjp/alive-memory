/**
 * TASK-095 v3.1 Batch 3: Single MCP server operations.
 *
 * PATCH  /api/agents/:id/mcp/:serverId — Toggle server enabled/disabled
 * DELETE /api/agents/:id/mcp/:serverId — Remove server
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { getAgentHealth, dashboardFetchRaw } from '@/lib/agent-client';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string; serverId: string }> }
) {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const { id, serverId } = await params;
  const owns = await db.agentBelongsToManager(id, managerId);
  if (!owns) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  const agent = await db.getAgent(id);
  if (!agent) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  const body = await request.json();
  if (body.enabled === undefined) {
    return NextResponse.json(
      { error: 'enabled field is required' },
      { status: 400 }
    );
  }

  const healthy = await getAgentHealth(id);
  if (!healthy) {
    return NextResponse.json({ error: 'agent offline' }, { status: 502 });
  }

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no api key' }, { status: 500 });
  }

  const { data, status } = await dashboardFetchRaw(
    id, keys[0].key, 'PATCH',
    `mcp/${encodeURIComponent(serverId)}`,
    { enabled: body.enabled }
  );

  if (status === 0) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }
  if (status >= 400) {
    return NextResponse.json({ error: data ?? 'engine error' }, { status });
  }

  return NextResponse.json(data);
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string; serverId: string }> }
) {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const { id, serverId } = await params;
  const owns = await db.agentBelongsToManager(id, managerId);
  if (!owns) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  const agent = await db.getAgent(id);
  if (!agent) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  const healthy = await getAgentHealth(id);
  if (!healthy) {
    return NextResponse.json({ error: 'agent offline' }, { status: 502 });
  }

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no api key' }, { status: 500 });
  }

  const { data, status } = await dashboardFetchRaw(
    id, keys[0].key, 'DELETE',
    `mcp/${encodeURIComponent(serverId)}`
  );

  if (status === 0) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }
  if (status >= 400) {
    return NextResponse.json({ error: data ?? 'engine error' }, { status });
  }

  return NextResponse.json(data);
}
