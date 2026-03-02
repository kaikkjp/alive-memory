/**
 * GET /api/agents/:id/channels — Channel status endpoint.
 *
 * TASK-095 v3.1 Batch 2 (2I): Returns status of communication channels
 * (API keys, WebSocket, RSS feeds, MCP servers).
 *
 * Aggregates data from multiple engine endpoints into a unified channel view.
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

  const apiKey = keys[0].key;

  // Fetch channel data in parallel — using dashboardFetchRaw to propagate 404
  const [feedsResult, capsResult] = await Promise.all([
    dashboardFetchRaw(id, apiKey, 'GET', 'feed/streams'),
    dashboardFetchRaw(id, apiKey, 'GET', 'capabilities'),
  ]);

  // If both sub-fetches returned 404, the engine doesn't support channels yet
  if (feedsResult.status === 404 && capsResult.status === 404) {
    return NextResponse.json({ error: 'not available yet' }, { status: 404 });
  }

  const feeds = feedsResult.status >= 200 && feedsResult.status < 300
    ? feedsResult.data : null;
  const capabilities = capsResult.status >= 200 && capsResult.status < 300
    ? capsResult.data : null;

  // Extract feed array — handle both array and { streams: [...] } forms
  const feedArr = Array.isArray(feeds)
    ? feeds
    : (feeds && typeof feeds === 'object' && 'streams' in feeds && Array.isArray((feeds as Record<string, unknown>).streams))
      ? (feeds as Record<string, unknown>).streams as Record<string, unknown>[]
      : [];
  const channels = [
    {
      channel: 'api',
      enabled: true,
      message_count: keys.length,
    },
    {
      channel: 'rss',
      enabled: feedArr.some((f: Record<string, unknown>) => f.active),
      message_count: feedArr.length,
    },
    {
      channel: 'websocket',
      enabled: true, // Always available when agent is online
    },
    {
      channel: 'mcp',
      enabled: false, // Batch 3 — not yet implemented
      message_count: 0,
    },
  ];

  return NextResponse.json({ channels, capabilities });
}
