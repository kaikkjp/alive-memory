/**
 * GET /api/auth/me — Return current manager info if authenticated, 401 otherwise.
 * Soft-auth: middleware passes through without auth but injects headers when possible.
 */

import { NextResponse } from 'next/server';
import { headers } from 'next/headers';

export async function GET() {
  const h = await headers();
  const managerId = h.get('x-manager-id');
  const managerName = h.get('x-manager-name');

  if (!managerId) {
    return NextResponse.json({ authenticated: false }, { status: 401 });
  }

  return NextResponse.json({
    authenticated: true,
    manager: { id: managerId, name: managerName || '' },
  });
}
