/**
 * Single RSS stream operations.
 *
 * TASK-095 v3.1 Batch 2 (2G): Per-stream PATCH/DELETE proxy.
 *
 * PATCH  /api/agents/:id/feed/streams/:streamId — Toggle active { active: bool }
 * DELETE /api/agents/:id/feed/streams/:streamId — Remove stream
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
  { params }: { params: Promise<{ id: string; streamId: string }> }
) {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const { id, streamId } = await params;
  const owns = await db.agentBelongsToManager(id, managerId);
  if (!owns) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  const agent = await db.getAgent(id);
  if (!agent) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  const body = await request.json();
  if (body.active === undefined) {
    return NextResponse.json(
      { error: 'active field is required' },
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
    `feed/streams/${encodeURIComponent(streamId)}`,
    { active: body.active }
  );

  if (status === 0) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }
  if (status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  if (status >= 400) {
    return NextResponse.json({ error: data ?? 'engine error' }, { status });
  }

  return NextResponse.json(data);
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string; streamId: string }> }
) {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const { id, streamId } = await params;
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
    `feed/streams/${encodeURIComponent(streamId)}`
  );

  if (status === 0) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }
  if (status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  if (status >= 400) {
    return NextResponse.json({ error: data ?? 'engine error' }, { status });
  }

  return NextResponse.json(data);
}
