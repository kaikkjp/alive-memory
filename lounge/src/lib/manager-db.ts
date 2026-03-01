/**
 * TASK-095 Phase 5: Manager portal SQLite database via sql.js (WASM).
 *
 * Tables:
 *   managers — login tokens + metadata
 *   agents   — agent registry (id, name, port, manager_id)
 *   api_keys — per-agent API keys
 *
 * Database file: data/lounge.db (created on first access)
 */

import initSqlJs from 'sql.js';
import type { Database } from 'sql.js';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import type { Manager, Agent, ApiKey } from './types';

const DB_PATH = path.join(process.cwd(), 'data', 'lounge.db');

let _db: Database | null = null;

async function getDb(): Promise<Database> {
  if (_db) return _db;

  const SQL = await initSqlJs({
    locateFile: (file: string) =>
      path.join(process.cwd(), 'node_modules', 'sql.js', 'dist', file),
  });
  const dir = path.dirname(DB_PATH);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  if (fs.existsSync(DB_PATH)) {
    const buffer = fs.readFileSync(DB_PATH);
    _db = new SQL.Database(buffer);
  } else {
    _db = new SQL.Database();
  }

  // Run migrations
  _db.run(`
    CREATE TABLE IF NOT EXISTS managers (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      token TEXT UNIQUE NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  _db.run(`
    CREATE TABLE IF NOT EXISTS agents (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT '',
      bio TEXT NOT NULL DEFAULT '',
      manager_id TEXT NOT NULL,
      port INTEGER NOT NULL,
      openrouter_key TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (manager_id) REFERENCES managers(id)
    )
  `);

  _db.run(`
    CREATE TABLE IF NOT EXISTS api_keys (
      id TEXT PRIMARY KEY,
      agent_id TEXT NOT NULL,
      key TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL DEFAULT 'default',
      rate_limit INTEGER NOT NULL DEFAULT 60,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
    )
  `);

  persist();
  return _db;
}

function persist(): void {
  if (!_db) return;
  const data = _db.export();
  const buffer = Buffer.from(data);
  fs.writeFileSync(DB_PATH, buffer);
}

// ── Manager operations ──

export async function validateManagerToken(token: string): Promise<Manager | null> {
  const db = await getDb();
  const result = db.exec('SELECT id, name, created_at FROM managers WHERE token = ?', [token]);
  if (!result.length || !result[0].values.length) return null;
  const [id, name, created_at] = result[0].values[0] as [string, string, string];
  return { id, name, created_at };
}

export async function getManager(id: string): Promise<Manager | null> {
  const db = await getDb();
  const result = db.exec('SELECT id, name, created_at FROM managers WHERE id = ?', [id]);
  if (!result.length || !result[0].values.length) return null;
  const [mid, name, created_at] = result[0].values[0] as [string, string, string];
  return { id: mid, name, created_at };
}

export async function createManager(name: string, token: string): Promise<Manager> {
  const db = await getDb();
  const id = crypto.randomUUID();
  db.run(
    'INSERT INTO managers (id, name, token) VALUES (?, ?, ?)',
    [id, name, token]
  );
  persist();
  return { id, name, created_at: new Date().toISOString() };
}

// ── Agent operations ──

export async function listAgents(managerId: string): Promise<Agent[]> {
  const db = await getDb();
  const result = db.exec(
    'SELECT id, name, role, manager_id, port, created_at, updated_at FROM agents WHERE manager_id = ? ORDER BY created_at DESC',
    [managerId]
  );
  if (!result.length) return [];
  return result[0].values.map((row) => ({
    id: row[0] as string,
    name: row[1] as string,
    role: (row[2] as string) || undefined,
    manager_id: row[3] as string,
    port: row[4] as number,
    status: 'stopped' as const, // Status determined at runtime
    created_at: row[5] as string,
    updated_at: row[6] as string,
  }));
}

export async function listAllAgents(): Promise<Agent[]> {
  const db = await getDb();
  const result = db.exec(
    'SELECT id, name, role, manager_id, port, created_at, updated_at FROM agents ORDER BY created_at DESC'
  );
  if (!result.length) return [];
  return result[0].values.map((row) => ({
    id: row[0] as string,
    name: row[1] as string,
    role: (row[2] as string) || undefined,
    manager_id: row[3] as string,
    port: row[4] as number,
    status: 'stopped' as const,
    created_at: row[5] as string,
    updated_at: row[6] as string,
  }));
}

export async function getAgent(id: string): Promise<Agent | null> {
  const db = await getDb();
  const result = db.exec(
    'SELECT id, name, role, manager_id, port, created_at, updated_at FROM agents WHERE id = ?',
    [id]
  );
  if (!result.length || !result[0].values.length) return null;
  const [aid, name, role, manager_id, port, created_at, updated_at] = result[0].values[0];
  return {
    id: aid as string,
    name: name as string,
    role: (role as string) || undefined,
    manager_id: manager_id as string,
    port: port as number,
    status: 'stopped',
    created_at: created_at as string,
    updated_at: updated_at as string,
  };
}

export async function createAgent(
  name: string,
  managerId: string,
  port: number,
  openrouterKey: string,
  role?: string,
  bio?: string
): Promise<Agent> {
  const db = await getDb();
  // Generate a URL-safe agent ID from the name
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 32);
  const suffix = crypto.randomBytes(4).toString('hex');
  const id = slug ? `${slug}-${suffix}` : `agent-${suffix}`;

  db.run(
    'INSERT INTO agents (id, name, role, bio, manager_id, port, openrouter_key) VALUES (?, ?, ?, ?, ?, ?, ?)',
    [id, name, role || '', bio || '', managerId, port, openrouterKey]
  );
  persist();
  return {
    id,
    name,
    role: role || undefined,
    manager_id: managerId,
    port,
    status: 'stopped',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

export async function deleteAgent(id: string): Promise<void> {
  const db = await getDb();
  db.run('DELETE FROM api_keys WHERE agent_id = ?', [id]);
  db.run('DELETE FROM agents WHERE id = ?', [id]);
  persist();
}

export async function getAgentOpenRouterKey(agentId: string): Promise<string> {
  const db = await getDb();
  const result = db.exec('SELECT openrouter_key FROM agents WHERE id = ?', [agentId]);
  if (!result.length || !result[0].values.length) return '';
  return result[0].values[0][0] as string;
}

// ── Port allocation ──

export async function getNextPort(): Promise<number> {
  const db = await getDb();
  const result = db.exec('SELECT MAX(port) FROM agents');
  if (!result.length || !result[0].values.length || result[0].values[0][0] === null) {
    return 9001; // First agent port
  }
  return (result[0].values[0][0] as number) + 1;
}

// ── API key operations ──

export async function listApiKeys(agentId: string): Promise<ApiKey[]> {
  const db = await getDb();
  const result = db.exec(
    'SELECT id, agent_id, key, name, rate_limit, created_at FROM api_keys WHERE agent_id = ? ORDER BY created_at DESC',
    [agentId]
  );
  if (!result.length) return [];
  return result[0].values.map((row) => ({
    id: row[0] as string,
    agent_id: row[1] as string,
    key: row[2] as string,
    name: row[3] as string,
    rate_limit: row[4] as number,
    created_at: row[5] as string,
  }));
}

export async function createApiKey(
  agentId: string,
  name: string,
  rateLimit: number = 60
): Promise<ApiKey> {
  const db = await getDb();
  const id = crypto.randomUUID();
  const key = `sk-live-${crypto.randomBytes(24).toString('hex')}`;

  db.run(
    'INSERT INTO api_keys (id, agent_id, key, name, rate_limit) VALUES (?, ?, ?, ?, ?)',
    [id, agentId, key, name, rateLimit]
  );
  persist();
  return { id, agent_id: agentId, key, name, rate_limit: rateLimit, created_at: new Date().toISOString() };
}

export async function deleteApiKey(keyId: string, agentId: string): Promise<void> {
  const db = await getDb();
  db.run('DELETE FROM api_keys WHERE id = ? AND agent_id = ?', [keyId, agentId]);
  persist();
}

/**
 * Sync all API keys for an agent to its api_keys.json config file.
 * The live agent reads this file; writing it keeps auth in sync without restart.
 */
export async function syncApiKeysToAgent(agentId: string): Promise<void> {
  const agentsRoot = process.env.AGENTS_ROOT || '/data/alive-agents';
  const keysPath = path.join(agentsRoot, agentId, 'api_keys.json');

  try {
    const keys = await listApiKeys(agentId);
    const payload = keys.map((k) => ({
      key: k.key,
      name: k.name,
      rate_limit: k.rate_limit,
    }));
    fs.writeFileSync(keysPath, JSON.stringify(payload, null, 2) + '\n');
    // Container runs as appuser (UID 1000) — ensure file is readable
    try { fs.chownSync(keysPath, 1000, 1000); } catch { /* non-root env */ }
  } catch {
    // Agent config dir may not exist yet (pre-container-start); skip silently
  }
}

// ── Ownership check ──

export async function agentBelongsToManager(agentId: string, managerId: string): Promise<boolean> {
  const db = await getDb();
  const result = db.exec(
    'SELECT 1 FROM agents WHERE id = ? AND manager_id = ?',
    [agentId, managerId]
  );
  return result.length > 0 && result[0].values.length > 0;
}
