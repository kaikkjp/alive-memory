/**
 * GET /api/agents/:id/status — Expanded state proxy.
 *
 * TASK-095 v2: Enhanced to include drives, mood, recent actions.
 * TASK-095 v3.1 Batch 2 (2B): Added organism_params, inner_voice, cycle_count,
 * engagement_state, current_action, is_sleeping from initial state broadcast.
 */

import { NextResponse } from 'next/server';
import * as db from '@/lib/manager-db';
import { getAgentStatus, getAgentHealth, dashboardGet } from '@/lib/agent-client';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const agent = await db.getAgent(id);
  if (!agent) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }

  // Check basic health first
  const healthy = await getAgentHealth(id);
  if (!healthy) {
    return NextResponse.json({
      status: 'offline',
    });
  }

  // Get API key for proxying
  const keys = await db.listApiKeys(id);
  if (keys.length === 0) {
    return NextResponse.json({
      status: 'active',
    });
  }

  const apiKey = keys[0].key;

  // Fetch public state (basic) and expanded drives in parallel
  const [publicState, drives, state] = await Promise.all([
    getAgentStatus(id, apiKey),
    dashboardGet(id, apiKey, 'drives'),
    dashboardGet(id, apiKey, 'state'),
  ]);

  // Merge into expanded response
  const result: Record<string, unknown> = {
    ...(publicState || { status: 'active' }),
    ...(drives ? { drives } : {}),
  };

  // Add lounge-specific fields from initial state
  if (state) {
    if (state.organism_params) result.organism_params = state.organism_params;
    if (state.inner_voice !== undefined) result.inner_voice = state.inner_voice;
    if (state.cycle_count !== undefined) result.cycle_count = state.cycle_count;
    if (state.engagement_state !== undefined) result.engagement_state = state.engagement_state;
    if (state.current_action !== undefined) result.current_action = state.current_action;
    if (state.is_sleeping !== undefined) result.is_sleeping = state.is_sleeping;
    if (state.drives) result.drives = state.drives;
    if (state.mood) result.mood = state.mood;
    if (state.energy !== undefined) result.energy = state.energy;
  }

  return NextResponse.json(result);
}
