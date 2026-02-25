/**
 * POST /api/agents/:id/stop — Stop an agent container.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { stopAgentContainer } from '@/lib/docker-client';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function POST(
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

  const result = await stopAgentContainer(id);
  return NextResponse.json({
    stopped: result.success,
    output: result.output,
    error: result.error,
  });
}
