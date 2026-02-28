/** REST helpers for initial page load. */

// In production (behind nginx), API is at the same origin under /api/.
// In development, fall back to the local heartbeat server.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export async function fetchInitialState() {
  const res = await fetch(`${API_BASE}/api/state`);
  if (!res.ok) {
    throw new Error(`Failed to fetch state: ${res.status}`);
  }
  return res.json();
}
