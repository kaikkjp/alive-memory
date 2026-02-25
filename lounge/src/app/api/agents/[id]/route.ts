/**
 * GET /api/agents/:id — Get agent details.
 * DELETE /api/agents/:id — Destroy an agent.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { destroyAgentContainer, isContainerRunning } from '@/lib/docker-client';

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

  const running = await isContainerRunning(id);

  return NextResponse.json({
    ...agent,
    status: running ? 'running' : 'stopped',
  });
}

export async function DELETE(
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

  // Destroy container and purge data
  const result = await destroyAgentContainer(id, true);

  // Remove from DB
  await db.deleteAgent(id);

  return NextResponse.json({ deleted: true, output: result.output });
}
