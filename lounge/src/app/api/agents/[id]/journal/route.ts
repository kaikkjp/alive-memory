/**
 * GET /api/agents/:id/journal — Journal entries proxy.
 * TASK-108: Proxies to engine's /api/dashboard/journal endpoint.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { getAgentHealth, dashboardGet } from '@/lib/agent-client';

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

  const result = await dashboardGet(id, keys[0].key, 'journal');
  if (!result) {
    return NextResponse.json({ error: 'agent not responding' }, { status: 502 });
  }

  return NextResponse.json(result);
}
