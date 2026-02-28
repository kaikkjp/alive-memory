/** API and WebSocket configuration. */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || '').replace(/\/$/, '');

export function getWsUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  if (typeof window === 'undefined') return 'ws://localhost:8765';
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/`;
}

export function getApiBase(): string {
  return API_BASE;
}

/** Max fragments kept in the activity stream DOM. */
export const MAX_FRAGMENTS = 8;

/** WebSocket reconnect timing. */
export const RECONNECT_BASE_MS = 1000;
export const RECONNECT_MAX_MS = 30000;

/** Expression sprite file map — keys match SpriteState type. */
export const SPRITE_MAP: Record<string, string> = {
  engaged: 'char-1-cropped.png',
  tired: 'char-2-cropped.png',
  thinking: 'char-3-cropped.png',
  curious: 'char-4-cropped.png',
  surprised: 'char-5-cropped.png',
  focused: 'char-6-cropped.png',
  // Spec expression mappings (aliases)
  smiling: 'char-1-cropped.png',
};

export const DEFAULT_EXPRESSION = 'thinking';
