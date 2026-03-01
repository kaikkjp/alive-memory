/**
 * POST /api/agents/:id/history — Proxy conversation history from agent container.
 * TASK-098: Returns past messages for a visitor_id so the lounge can restore chat on reload.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { getConversationHistory } from '@/lib/agent-client';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
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

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no API key configured' }, { status: 500 });
  }

  try {
    const body = await request.json();
    // Use stable manager-derived visitor_id, same as chat proxy
    const stableVisitorId = `mgr-${managerId}`;
    const result = await getConversationHistory(
      agent.port,
      keys[0].key,
      stableVisitorId,
      body.limit
    );

    if (result) {
      return NextResponse.json(result);
    }
    return NextResponse.json({ messages: [], visitor_id: stableVisitorId });
  } catch {
    return NextResponse.json({ error: 'history fetch failed' }, { status: 500 });
  }
}
