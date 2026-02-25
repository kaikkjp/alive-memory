/**
 * PATCH /api/agents/:id/config — Update agent configuration.
 *
 * Updates identity.yaml and/or alive_config.yaml in the agent's config dir,
 * then restarts the container.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';
import fs from 'fs';
import path from 'path';
import * as db from '@/lib/manager-db';
import { stopAgentContainer, startAgentContainer } from '@/lib/docker-client';

const AGENTS_ROOT = process.env.AGENTS_ROOT || '/data/agents';

async function getManagerId(): Promise<string | null> {
  const h = await headers();
  return h.get('x-manager-id');
}

export async function PATCH(
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
    const body = await request.json();
    const configDir = path.join(AGENTS_ROOT, id);

    if (!fs.existsSync(configDir)) {
      return NextResponse.json({ error: 'agent config dir not found' }, { status: 404 });
    }

    // Update identity.yaml if identity fields provided
    if (body.identity) {
      const identityPath = path.join(configDir, 'identity.yaml');
      // Simple YAML serialization for identity fields
      const yaml = Object.entries(body.identity)
        .map(([key, value]) => {
          if (Array.isArray(value)) {
            return `${key}:\n${(value as string[]).map((v) => `  - "${v}"`).join('\n')}`;
          }
          if (typeof value === 'string' && value.includes('\n')) {
            return `${key}: |\n${value.split('\n').map((l) => `  ${l}`).join('\n')}`;
          }
          return `${key}: "${value}"`;
        })
        .join('\n\n');
      fs.writeFileSync(identityPath, yaml + '\n');
    }

    // Restart container to pick up changes
    await stopAgentContainer(id);
    await startAgentContainer(id);

    return NextResponse.json({ updated: true, restarted: true });
  } catch {
    return NextResponse.json({ error: 'failed to update config' }, { status: 500 });
  }
}
