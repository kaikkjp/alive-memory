/**
 * GET /api/agents/:id/stream — SSE stream proxy.
 *
 * TASK-095 v3.1 Batch 2 (2A): Bridges engine state to browser via Server-Sent Events.
 *
 * Current implementation: HTTP polling → SSE bridge (polls /api/dashboard/state every 5s).
 * Future upgrade: WebSocket → SSE bridge when WS port is exposed from containers.
 *
 * The frontend connects once via EventSource and receives scene_update events.
 * On disconnect, the frontend falls back to REST polling at 30s intervals.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { agentDashboardUrl, getGatewayHeaders } from '@/lib/agent-client';

const POLL_INTERVAL_MS = 5_000;
const POLL_TIMEOUT_MS = 8_000;

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

  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({ error: 'no api key' }, { status: 500 });
  }

  const apiKey = keys[0].key;
  const stateUrl = agentDashboardUrl(id, 'state');
  const hdrs = getGatewayHeaders(apiKey);

  const encoder = new TextEncoder();
  let aborted = false;

  // Listen for client disconnect
  request.signal.addEventListener('abort', () => {
    aborted = true;
  });

  function emit(controller: ReadableStreamDefaultController, chunk: string) {
    if (aborted) return;
    try {
      controller.enqueue(encoder.encode(chunk));
    } catch {
      // Controller already closed (client disconnected) — exit cleanly
      aborted = true;
    }
  }

  const stream = new ReadableStream({
    async start(controller) {
      emit(controller, ': connected\n\n');

      while (!aborted) {
        try {
          const res = await fetch(stateUrl, {
            headers: hdrs,
            signal: AbortSignal.timeout(POLL_TIMEOUT_MS),
          });

          if (res.ok) {
            const data = await res.json();
            emit(controller, `data: ${JSON.stringify(data)}\n\n`);
          } else {
            emit(controller, `event: error\ndata: ${JSON.stringify({ status: 'agent_error', code: res.status })}\n\n`);
          }
        } catch {
          // Agent offline — unnamed event so onmessage always receives it
          emit(controller, `data: ${JSON.stringify({ type: 'agent_offline', status: 'offline' })}\n\n`);
        }

        if (!aborted) {
          await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
        }
      }

      try { controller.close(); } catch { /* already closed */ }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}

// Prevent Next.js from caching this route
export const dynamic = 'force-dynamic';
