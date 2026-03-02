/**
 * TASK-095 v2: Whisper queue endpoints.
 * TASK-095 v3.1 Batch 2 (2C): Added DELETE for canceling pending whispers.
 *
 * GET    /api/agents/:id/whispers — List pending whispers
 * POST   /api/agents/:id/whispers — Create a new whisper (queue config change)
 * DELETE /api/agents/:id/whispers — Cancel a pending whisper { whisper_id }
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { getAgentHealth, dashboardGet, dashboardPost, dashboardDelete } from '@/lib/agent-client';

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

  const healthy = await getAgentHealth(id);
  if (!healthy) {
    return NextResponse.json({ error: 'agent offline' }, { status: 502 });
  }

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no api key' }, { status: 500 });
  }

  const result = await dashboardGet(id, keys[0].key, 'whispers');
  if (!result) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }

  return NextResponse.json(result);
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
  if (!body.param_path || body.new_value === undefined) {
    return NextResponse.json(
      { error: 'param_path and new_value are required' },
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

  const result = await dashboardPost(id, keys[0].key, 'whispers', {
    param_path: body.param_path,
    new_value: body.new_value,
  });

  if (!result) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }

  return NextResponse.json(result, { status: 201 });
}

export async function DELETE(
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
  if (!body.whisper_id) {
    return NextResponse.json(
      { error: 'whisper_id is required' },
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

  const result = await dashboardDelete(
    id,
    keys[0].key,
    `whispers/${encodeURIComponent(body.whisper_id)}`
  );

  if (!result) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }

  return NextResponse.json(result);
}
