/**
 * GET /api/agents/:id/inner-voice — Inner voice history proxy.
 *
 * TASK-095 v3.1 Batch 2 (2H): Proxies to engine's /api/dashboard/inner-voice endpoint.
 * Returns paginated internal monologue entries.
 *
 * Query params:
 *   limit  — max entries (default 20, max 100)
 *   before — ISO timestamp for cursor pagination
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

  // Forward query params
  const url = new URL(request.url);
  const limit = url.searchParams.get('limit');
  const before = url.searchParams.get('before');

  let path = 'inner-voice';
  const queryParts: string[] = [];
  if (limit) queryParts.push(`limit=${encodeURIComponent(limit)}`);
  if (before) queryParts.push(`before=${encodeURIComponent(before)}`);
  if (queryParts.length > 0) path += `?${queryParts.join('&')}`;

  const { data, status } = await dashboardFetchRaw(id, keys[0].key, 'GET', path);

  if (status === 0) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }
  if (status >= 400) {
    return NextResponse.json({ error: data ?? 'engine error' }, { status });
  }

  return NextResponse.json(data ?? { entries: [] });
}
