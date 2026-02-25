/**
 * GET /api/agents/:id/config — Read agent identity config.
 * PATCH /api/agents/:id/config — Update agent configuration + restart.
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

/**
 * Minimal YAML parser for identity.yaml (flat key-value + arrays only).
 */
function parseSimpleYaml(text: string): Record<string, string | string[]> {
  const result: Record<string, string | string[]> = {};
  let currentKey = '';
  let currentBlock: string[] = [];
  let inBlock = false;
  let inArray = false;

  for (const line of text.split('\n')) {
    // Array item
    if (inArray && /^\s+-\s+/.test(line)) {
      const val = line.replace(/^\s+-\s+/, '').replace(/^["']|["']$/g, '');
      (result[currentKey] as string[]).push(val);
      continue;
    }

    // Block scalar continuation
    if (inBlock && /^\s{2}/.test(line)) {
      currentBlock.push(line.replace(/^\s{2}/, ''));
      continue;
    }

    // Flush block
    if (inBlock) {
      result[currentKey] = currentBlock.join('\n');
      inBlock = false;
      currentBlock = [];
    }
    inArray = false;

    // New key
    const match = line.match(/^([a-z_]+):\s*(.*)/);
    if (!match) continue;

    const [, key, rest] = match;
    currentKey = key;

    if (rest === '|' || rest === '>') {
      inBlock = true;
      currentBlock = [];
    } else if (rest === '' || rest.trim() === '') {
      // Could be array or empty
      result[key] = [];
      inArray = true;
    } else {
      result[key] = rest.replace(/^["']|["']$/g, '');
    }
  }

  // Flush final block
  if (inBlock) {
    result[currentKey] = currentBlock.join('\n');
  }

  return result;
}

/**
 * Escape a string for safe YAML output (double-quoted scalar).
 */
function yamlEscape(s: string): string {
  return s.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
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

  const identityPath = path.join(AGENTS_ROOT, id, 'identity.yaml');
  if (!fs.existsSync(identityPath)) {
    return NextResponse.json({ config: {} });
  }

  try {
    const raw = fs.readFileSync(identityPath, 'utf-8');
    const config = parseSimpleYaml(raw);
    return NextResponse.json({ config });
  } catch {
    return NextResponse.json({ config: {} });
  }
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
      const yaml = Object.entries(body.identity)
        .map(([key, value]) => {
          if (Array.isArray(value)) {
            return `${key}:\n${(value as string[]).map((v) => `  - "${yamlEscape(String(v))}"`).join('\n')}`;
          }
          if (typeof value === 'string' && value.includes('\n')) {
            return `${key}: |\n${value.split('\n').map((l) => `  ${l}`).join('\n')}`;
          }
          return `${key}: "${yamlEscape(String(value))}"`;
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
