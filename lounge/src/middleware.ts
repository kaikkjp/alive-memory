/**
 * TASK-095 Phase 5: Session validation middleware.
 *
 * Protects /api/* routes (except /api/auth/*) and /dashboard/*
 * by verifying JWT session cookies.
 */

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { jwtVerify } from 'jose';

const PUBLIC_PATHS = [
  '/api/auth/login',
  '/login',
  '/',
  '/organism-test',
  '/canvas-test',
];

// Soft-auth paths: accessible without login, but inject manager headers if a
// valid session cookie exists. Use exact match to avoid opening sub-routes
// (e.g. /api/agents/:id/start must stay protected).
const SOFT_AUTH_EXACT = [
  '/dashboard',
  '/api/agents',
  '/api/auth/me',
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'));
}

function isSoftAuthPath(pathname: string): boolean {
  if (SOFT_AUTH_EXACT.includes(pathname)) return true;
  // Allow public read of agent status for dashboard vitals
  if (/^\/api\/agents\/[^/]+\/status$/.test(pathname)) return true;
  return false;
}

/** Try to extract manager info from JWT; returns headers with x-manager-* if valid. */
async function tryInjectManager(
  request: NextRequest,
  secret: string
): Promise<NextResponse | null> {
  const token = request.cookies.get('lounge_session')?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, new TextEncoder().encode(secret));
    if (!payload.sub) return null;
    const requestHeaders = new Headers(request.headers);
    requestHeaders.set('x-manager-id', payload.sub);
    requestHeaders.set('x-manager-name', (payload.name as string) || '');
    return NextResponse.next({ request: { headers: requestHeaders } });
  } catch {
    return null;
  }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // Allow static assets
  if (pathname.startsWith('/_next') || pathname.includes('.')) {
    return NextResponse.next();
  }

  const secret = process.env.LOUNGE_JWT_SECRET;

  // Soft-auth: pass through even without login, but inject manager if possible.
  // IMPORTANT: always strip inbound x-manager-* headers to prevent spoofing.
  if (isSoftAuthPath(pathname)) {
    if (secret) {
      const enriched = await tryInjectManager(request, secret);
      if (enriched) return enriched;
    }
    // No valid JWT — strip any spoofed manager headers
    const sanitized = new Headers(request.headers);
    sanitized.delete('x-manager-id');
    sanitized.delete('x-manager-name');
    return NextResponse.next({ request: { headers: sanitized } });
  }

  // ── Protected routes below ──

  // Check session cookie
  const token = request.cookies.get('lounge_session')?.value;
  if (!token) {
    // API routes return 401, pages redirect to login
    if (pathname.startsWith('/api/')) {
      return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
    }
    return NextResponse.redirect(new URL('/login', request.url));
  }

  // Verify JWT
  if (!secret) {
    return NextResponse.json({ error: 'server misconfigured' }, { status: 500 });
  }

  try {
    const { payload } = await jwtVerify(
      token,
      new TextEncoder().encode(secret)
    );
    if (!payload.sub) {
      throw new Error('missing subject');
    }

    // Attach manager info to request headers for downstream route handlers
    const requestHeaders = new Headers(request.headers);
    requestHeaders.set('x-manager-id', payload.sub);
    requestHeaders.set('x-manager-name', (payload.name as string) || '');
    return NextResponse.next({
      request: { headers: requestHeaders },
    });
  } catch {
    // Invalid/expired token
    if (pathname.startsWith('/api/')) {
      return NextResponse.json({ error: 'session expired' }, { status: 401 });
    }
    return NextResponse.redirect(new URL('/login', request.url));
  }
}

export const config = {
  matcher: [
    // Match all paths except static files
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
