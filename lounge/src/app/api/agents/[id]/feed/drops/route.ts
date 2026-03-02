/**
 * Feed drop endpoints.
 *
 * TASK-095 v3.1 Batch 2 (2G): Proxy for manual content injection.
 *
 * GET  /api/agents/:id/feed/drops — List manager drops with consumption status
 * POST /api/agents/:id/feed/drops — Drop content (URL or text) into agent's feed
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { getAgentHealth, dashboardFetchRaw } from '@/lib/agent-client';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function GET(
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

  const healthy = await getAgentHealth(id);
  if (!healthy) {
    return NextResponse.json({ error: 'agent offline' }, { status: 502 });
  }

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no api key' }, { status: 500 });
  }

  // Forward limit param
  const url = new URL(request.url);
  const limit = url.searchParams.get('limit');
  let path = 'feed/drops';
  if (limit) path += `?limit=${encodeURIComponent(limit)}`;

  const { data, status } = await dashboardFetchRaw(id, keys[0].key, 'GET', path);

  if (status === 0) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }
  if (status >= 400) {
    return NextResponse.json({ error: data ?? 'engine error' }, { status });
  }

  return NextResponse.json(data ?? { drops: [] });
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
  if (!body.title || (!body.url && !body.text)) {
    return NextResponse.json(
      { error: 'title and either url or text are required' },
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

  const { data, status } = await dashboardFetchRaw(id, keys[0].key, 'POST', 'feed/drop', {
    title: body.title,
    ...(body.url ? { url: body.url } : {}),
    ...(body.text ? { text: body.text } : {}),
  });

  if (status === 0) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }
  if (status >= 400) {
    return NextResponse.json({ error: data ?? 'engine error' }, { status });
  }

  return NextResponse.json(data, { status: 201 });
}
