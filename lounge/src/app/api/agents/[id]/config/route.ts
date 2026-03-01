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

const AGENTS_ROOT = process.env.AGENTS_ROOT || '/data/alive-agents';

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
      const val = yamlUnescape(line.replace(/^\s+-\s+/, '').replace(/^["']|["']$/g, ''));
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
      result[key] = yamlUnescape(rest.replace(/^["']|["']$/g, ''));
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

/**
 * Unescape a YAML double-quoted scalar value.
 */
function yamlUnescape(s: string): string {
  return s.replace(/\\"/g, '"').replace(/\\\\/g, '\\');
}

/**
 * Full YAML parser that handles nested mappings, arrays, and scalars.
 * Covers the identity.yaml structure (2 levels of nesting max).
 */
function parseFullYaml(text: string): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  const lines = text.split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    // Skip empty/comment lines
    if (!line.trim() || line.trim().startsWith('#')) { i++; continue; }
    // Must be a top-level key (no leading whitespace)
    const topMatch = line.match(/^([a-z_]+):\s*(.*)/);
    if (!topMatch) { i++; continue; }

    const key = topMatch[1];
    const rest = topMatch[2].trim();

    if (rest === '|' || rest === '>') {
      // Block scalar
      const block: string[] = [];
      i++;
      while (i < lines.length && /^\s{2}/.test(lines[i])) {
        block.push(lines[i].replace(/^\s{2}/, ''));
        i++;
      }
      result[key] = block.join('\n') + (block.length ? '\n' : '');
    } else if (rest === '' || rest === '{}' || rest === '[]') {
      // Could be nested mapping, array, or empty
      i++;
      if (i < lines.length && /^\s+-\s/.test(lines[i])) {
        // Array
        const arr: unknown[] = [];
        while (i < lines.length && /^\s+-\s/.test(lines[i])) {
          const item = lines[i].replace(/^\s+-\s+/, '').replace(/^["']|["']$/g, '');
          arr.push(yamlScalar(item));
          i++;
        }
        result[key] = arr;
      } else if (i < lines.length && /^\s{2}\S/.test(lines[i])) {
        // Nested mapping
        const obj: Record<string, unknown> = {};
        while (i < lines.length && /^\s{2}\S/.test(lines[i])) {
          const subMatch = lines[i].match(/^\s{2}([a-z_]+):\s*(.*)/);
          if (!subMatch) { i++; continue; }
          const subKey = subMatch[1];
          const subRest = subMatch[2].trim();
          if (subRest === '|' || subRest === '>') {
            const block: string[] = [];
            i++;
            while (i < lines.length && /^\s{4}/.test(lines[i])) {
              block.push(lines[i].replace(/^\s{4}/, ''));
              i++;
            }
            obj[subKey] = block.join('\n') + (block.length ? '\n' : '');
          } else if (subRest.startsWith('[') && subRest.endsWith(']')) {
            // Inline array: [a, b, c]
            obj[subKey] = subRest.slice(1, -1).split(',').map(s => yamlScalar(s.trim()));
            i++;
          } else if (subRest === '') {
            // Sub-array
            i++;
            const arr: unknown[] = [];
            while (i < lines.length && /^\s{2,}-\s/.test(lines[i]) && !/^\s{2}[a-z]/.test(lines[i])) {
              arr.push(yamlScalar(lines[i].replace(/^\s+-\s+/, '').replace(/^["']|["']$/g, '')));
              i++;
            }
            obj[subKey] = arr;
          } else {
            obj[subKey] = yamlScalar(subRest.replace(/^["']|["']$/g, ''));
            i++;
          }
        }
        result[key] = obj;
      } else {
        result[key] = rest === '[]' ? [] : rest === '{}' ? {} : rest === '' ? null : rest;
      }
    } else {
      // Inline scalar
      result[key] = yamlScalar(rest.replace(/^["']|["']$/g, ''));
      i++;
    }
  }
  return result;
}

/** Parse a YAML scalar string into its JS type. */
function yamlScalar(s: string): string | number | boolean | null {
  if (s === 'true') return true;
  if (s === 'false') return false;
  if (s === 'null' || s === '~' || s === '') return s === '' ? '' : null;
  const n = Number(s);
  if (!isNaN(n) && s !== '') return n;
  return yamlUnescape(s);
}

/**
 * Serialize a JS object to YAML (identity.yaml-compatible).
 * Handles: scalars, arrays, nested mappings (1 level deep).
 */
function serializeYaml(obj: Record<string, unknown>): string {
  const parts: string[] = [];

  for (const [key, value] of Object.entries(obj)) {
    if (value === null || value === undefined) {
      parts.push(`${key}:`);
    } else if (Array.isArray(value)) {
      if (value.length === 0) {
        parts.push(`${key}: []`);
      } else {
        const items = value.map(v => `  - "${yamlEscape(String(v))}"`).join('\n');
        parts.push(`${key}:\n${items}`);
      }
    } else if (typeof value === 'object') {
      const sub = serializeSubMapping(value as Record<string, unknown>);
      parts.push(`${key}:\n${sub}`);
    } else if (typeof value === 'string' && value.includes('\n')) {
      const block = value.split('\n').map(l => `  ${l}`).join('\n');
      parts.push(`${key}: |\n${block}`);
    } else if (typeof value === 'boolean' || typeof value === 'number') {
      parts.push(`${key}: ${value}`);
    } else {
      parts.push(`${key}: "${yamlEscape(String(value))}"`);
    }
  }

  return parts.join('\n') + '\n';
}

function serializeSubMapping(obj: Record<string, unknown>): string {
  const lines: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined) {
      lines.push(`  ${k}:`);
    } else if (Array.isArray(v)) {
      if (v.length === 0) {
        lines.push(`  ${k}: []`);
      } else {
        lines.push(`  ${k}:`);
        for (const item of v) lines.push(`    - ${item}`);
      }
    } else if (typeof v === 'string' && v.includes('\n')) {
      lines.push(`  ${k}: |`);
      for (const l of v.split('\n')) lines.push(`    ${l}`);
    } else if (typeof v === 'boolean' || typeof v === 'number') {
      lines.push(`  ${k}: ${v}`);
    } else {
      lines.push(`  ${k}: "${yamlEscape(String(v))}"`);
    }
  }
  return lines.join('\n');
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

      // Read existing YAML so we merge rather than overwrite —
      // the UI only sends a subset of fields; naive overwrite drops
      // structured fields like world/voice_detection/manager_interaction.
      let existing: Record<string, unknown> = {};
      if (fs.existsSync(identityPath)) {
        try {
          existing = parseFullYaml(fs.readFileSync(identityPath, 'utf-8'));
        } catch { /* start fresh */ }
      }

      const merged = { ...existing, ...body.identity };
      const yaml = serializeYaml(merged);
      fs.writeFileSync(identityPath, yaml);
      // Container runs as appuser (UID 1000) — needs write access for capability toggles
      try { fs.chownSync(identityPath, 1000, 1000); } catch { /* non-root env */ }
    }

    // Restart container to pick up changes
    await stopAgentContainer(id);
    await startAgentContainer(id);

    return NextResponse.json({ updated: true, restarted: true });
  } catch {
    return NextResponse.json({ error: 'failed to update config' }, { status: 500 });
  }
}
