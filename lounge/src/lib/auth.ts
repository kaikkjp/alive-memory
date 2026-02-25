/**
 * TASK-095 Phase 5: JWT-based session management for manager portal.
 *
 * Uses signed JWT cookies (stateless). Manager tokens are pre-generated
 * and stored in the manager DB. Login flow:
 *   1. Manager enters their token
 *   2. Server validates against DB
 *   3. Server sets a signed JWT session cookie
 *   4. Subsequent requests validated via middleware
 */

import { SignJWT, jwtVerify } from 'jose';
import { cookies } from 'next/headers';

const SESSION_COOKIE = 'lounge_session';
const SESSION_DURATION = 7 * 24 * 60 * 60; // 7 days in seconds

function getSecret(): Uint8Array {
  const secret = process.env.LOUNGE_JWT_SECRET;
  if (!secret) {
    throw new Error('LOUNGE_JWT_SECRET environment variable is required');
  }
  return new TextEncoder().encode(secret);
}

export async function createSession(managerId: string, managerName: string): Promise<string> {
  const token = await new SignJWT({ sub: managerId, name: managerName })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuedAt()
    .setExpirationTime(`${SESSION_DURATION}s`)
    .sign(getSecret());

  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: SESSION_DURATION,
    path: '/',
  });

  return token;
}

export async function getSession(): Promise<{ managerId: string; name: string } | null> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  if (!token) return null;

  try {
    const { payload } = await jwtVerify(token, getSecret());
    if (!payload.sub) return null;
    return {
      managerId: payload.sub,
      name: (payload.name as string) || '',
    };
  } catch {
    return null;
  }
}

export async function clearSession(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE);
}
