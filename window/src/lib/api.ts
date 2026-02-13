/** REST helpers for initial page load. */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export async function fetchInitialState() {
  const res = await fetch(`${API_BASE}/api/state`);
  if (!res.ok) {
    throw new Error(`Failed to fetch state: ${res.status}`);
  }
  return res.json();
}
