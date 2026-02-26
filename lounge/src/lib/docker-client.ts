/**
 * TASK-095 Phase 5: Docker lifecycle operations for agent containers.
 *
 * Shells out to the lifecycle scripts created in Phase 4.
 * All operations are async and return structured results.
 */

import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const exec = promisify(execFile);

// ALIVE_ENGINE_DIR points to the engine repo root (where scripts/ lives).
// Falls back to parent of cwd for dev (lounge/ lives inside the repo).
const PROJECT_ROOT = process.env.ALIVE_ENGINE_DIR || path.resolve(process.cwd(), '..');
const SCRIPTS = path.join(PROJECT_ROOT, 'scripts');

export interface DockerResult {
  success: boolean;
  output: string;
  error?: string;
}

export async function createAgentContainer(
  agentId: string,
  port: number,
  apiKey: string,
  openrouterKey: string
): Promise<DockerResult> {
  try {
    // create_agent.sh takes: agent_id port openrouter_key
    // The lounge API key is synced separately via syncApiKeysToAgent
    const { stdout, stderr } = await exec(
      path.join(SCRIPTS, 'create_agent.sh'),
      [agentId, String(port), openrouterKey],
      { timeout: 120_000, cwd: PROJECT_ROOT }
    );
    return { success: true, output: stdout + stderr };
  } catch (err: unknown) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return {
      success: false,
      output: (e.stdout || '') + (e.stderr || ''),
      error: e.message || 'create_agent.sh failed',
    };
  }
}

export async function destroyAgentContainer(
  agentId: string,
  purge: boolean = false
): Promise<DockerResult> {
  try {
    const args = [agentId];
    if (purge) args.push('--purge');
    const { stdout, stderr } = await exec(
      path.join(SCRIPTS, 'destroy_agent.sh'),
      args,
      { timeout: 30_000, cwd: PROJECT_ROOT }
    );
    return { success: true, output: stdout + stderr };
  } catch (err: unknown) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return {
      success: false,
      output: (e.stdout || '') + (e.stderr || ''),
      error: e.message || 'destroy_agent.sh failed',
    };
  }
}

export async function startAgentContainer(agentId: string): Promise<DockerResult> {
  try {
    const { stdout, stderr } = await exec(
      'docker', ['start', `alive-agent-${agentId}`],
      { timeout: 15_000 }
    );
    return { success: true, output: stdout + stderr };
  } catch (err: unknown) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return {
      success: false,
      output: (e.stdout || '') + (e.stderr || ''),
      error: e.message || 'docker start failed',
    };
  }
}

export async function stopAgentContainer(agentId: string): Promise<DockerResult> {
  try {
    const { stdout, stderr } = await exec(
      'docker', ['stop', `alive-agent-${agentId}`],
      { timeout: 15_000 }
    );
    return { success: true, output: stdout + stderr };
  } catch (err: unknown) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return {
      success: false,
      output: (e.stdout || '') + (e.stderr || ''),
      error: e.message || 'docker stop failed',
    };
  }
}

export async function getAgentLogs(agentId: string, tail: number = 200): Promise<string> {
  try {
    const { stdout } = await exec(
      'docker', ['logs', '--tail', String(tail), `alive-agent-${agentId}`],
      { timeout: 10_000 }
    );
    return stdout;
  } catch (err: unknown) {
    const e = err as { stdout?: string; stderr?: string };
    // docker logs sends output to stderr for some logs
    return (e.stdout || '') + (e.stderr || '');
  }
}

export async function isContainerRunning(agentId: string): Promise<boolean> {
  try {
    const { stdout } = await exec(
      'docker', ['ps', '--filter', `name=alive-agent-${agentId}`, '--format', '{{.Names}}'],
      { timeout: 5_000 }
    );
    return stdout.trim() === `alive-agent-${agentId}`;
  } catch {
    return false;
  }
}
