/**
 * POST /api/agents/:id/chat — Proxy chat to agent container (for lounge UI).
 *
 * TASK-104: Uses /api/manager-message endpoint which bypasses the engagement
 * system. Manager messages don't create engagements or trigger ghost detection.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { managerMessage } from '@/lib/agent-client';

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

  // Get first API key
  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no API key configured' }, { status: 500 });
  }

  try {
    const body = await request.json();
    // Stable visitor_id: derived from managerId so the same manager always
    // maps to the same visitor across sessions, browsers, and devices.
    const stableVisitorId = `mgr-${managerId}`;
    const result = await managerMessage(
      id,
      keys[0].key,
      body.message,
      stableVisitorId
    );

    if (result) {
      return NextResponse.json({ ...result, visitor_id: stableVisitorId });
    }
    return NextResponse.json(
      { response: null, message: 'Agent is not responding' },
      { status: 200 }
    );
  } catch {
    return NextResponse.json({ error: 'chat failed' }, { status: 500 });
  }
}
