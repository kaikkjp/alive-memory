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
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'));
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
  const secret = process.env.LOUNGE_JWT_SECRET;
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
