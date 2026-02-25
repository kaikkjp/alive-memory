/**
 * GET /api/agents/:id/api-keys — List API keys for an agent.
 * POST /api/agents/:id/api-keys — Create a new API key.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';
import { syncApiKeysToAgent } from '@/lib/manager-db';
import type { CreateApiKeyRequest } from '@/lib/types';

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

  const keys = await db.listApiKeys(id);

  // Mask key values (show first 8 and last 4 chars)
  const masked = keys.map((k) => ({
    ...k,
    key: k.key.slice(0, 12) + '...' + k.key.slice(-4),
  }));

  return NextResponse.json({ api_keys: masked });
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

  try {
    const body: CreateApiKeyRequest = await request.json();
    const name = body.name?.trim() || 'unnamed';
    const rateLimit = body.rate_limit || 60;

    const key = await db.createApiKey(id, name, rateLimit);

    // Sync to live agent config
    await syncApiKeysToAgent(id);

    // Return the full key only on creation (never shown again)
    return NextResponse.json({ api_key: key }, { status: 201 });
  } catch {
    return NextResponse.json({ error: 'failed to create key' }, { status: 500 });
  }
}
