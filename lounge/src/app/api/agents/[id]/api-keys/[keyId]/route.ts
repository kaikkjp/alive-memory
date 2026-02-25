/**
 * DELETE /api/agents/:id/api-keys/:keyId — Revoke an API key.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import * as db from '@/lib/manager-db';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string; keyId: string }> }
) {
  const managerId = await getManagerId();
  if (!managerId) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const { id, keyId } = await params;
  const owns = await db.agentBelongsToManager(id, managerId);
  if (!owns) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  await db.deleteApiKey(keyId);
  return NextResponse.json({ deleted: true });
}
