/**
 * POST /api/auth/login — Authenticate manager with token.
 */

import { NextResponse } from 'next/server';
import { createSession } from '@/lib/auth';
import { validateManagerToken } from '@/lib/manager-db';

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const token = body.token?.trim();

    if (!token) {
      return NextResponse.json({ error: 'token required' }, { status: 400 });
    }

    const manager = await validateManagerToken(token);
    if (!manager) {
      return NextResponse.json({ error: 'invalid token' }, { status: 401 });
    }

    await createSession(manager.id, manager.name);

    return NextResponse.json({
      authenticated: true,
      manager: { id: manager.id, name: manager.name },
    });
  } catch {
    return NextResponse.json({ error: 'login failed' }, { status: 500 });
  }
}
