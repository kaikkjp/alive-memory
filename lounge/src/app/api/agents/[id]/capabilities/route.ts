/**
 * TASK-095 v2: Capabilities management endpoints.
 *
 * GET   /api/agents/:id/capabilities — List all actions + enabled state
 * PATCH /api/agents/:id/capabilities — Toggle action enabled/disabled
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { getAgentHealth, dashboardGet, dashboardPost } from '@/lib/agent-client';

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

  const healthy = await getAgentHealth(agent.port);
  if (!healthy) {
    return NextResponse.json({ error: 'agent offline' }, { status: 502 });
  }

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no api key' }, { status: 500 });
  }

  const result = await dashboardGet(agent.port, keys[0].key, 'capabilities');
  if (!result) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }

  return NextResponse.json(result);
}

export async function PATCH(
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
  if (!body.action || body.enabled === undefined) {
    return NextResponse.json(
      { error: 'action and enabled are required' },
      { status: 400 }
    );
  }

  const healthy = await getAgentHealth(agent.port);
  if (!healthy) {
    return NextResponse.json({ error: 'agent offline' }, { status: 502 });
  }

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no api key' }, { status: 500 });
  }

  // Use POST to the capabilities endpoint with the toggle payload
  // (dashboardPost handles Content-Type and auth)
  const result = await dashboardPost(agent.port, keys[0].key, 'capabilities', {
    action: body.action,
    enabled: body.enabled,
  });

  if (!result) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }

  return NextResponse.json(result);
}
