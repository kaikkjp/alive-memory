/**
 * TASK-095 v2: Memory CRUD endpoints.
 *
 * GET  /api/agents/:id/memories — List memories (filterable by origin)
 * POST /api/agents/:id/memories — Inject backstory memory
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

  // Pass query params through (origin, limit, offset)
  const url = new URL(request.url);
  const origin = url.searchParams.get('origin');
  const limit = url.searchParams.get('limit');
  const offset = url.searchParams.get('offset');

  let path = 'memories';
  const queryParts: string[] = [];
  if (origin) queryParts.push(`origin=${encodeURIComponent(origin)}`);
  if (limit) queryParts.push(`limit=${encodeURIComponent(limit)}`);
  if (offset) queryParts.push(`offset=${encodeURIComponent(offset)}`);
  if (queryParts.length > 0) path += `?${queryParts.join('&')}`;

  const result = await dashboardGet(id, keys[0].key, path);
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
  if (!body.text) {
    return NextResponse.json(
      { error: 'text is required' },
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

  const result = await dashboardPost(id, keys[0].key, 'memories', {
    text: body.text,
    ...(body.title ? { title: body.title } : {}),
  });

  if (!result) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }

  return NextResponse.json(result, { status: 201 });
}
