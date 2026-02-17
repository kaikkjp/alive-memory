/**
 * Dashboard API client with configurable backend URL.
 *
 * Reads NEXT_PUBLIC_DASHBOARD_API_URL from env, falls back to localhost.
 */

import { authManager } from './auth-manager';

const API_BASE =
  process.env.NEXT_PUBLIC_DASHBOARD_API_URL ?? '';

export async function dashboardFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  // Add Authorization header if session token is stored
  const token = authManager.getToken();
  const headers = new Headers(options.headers);

  if (token && !path.endsWith('/auth')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  // Handle auth failures (expired/invalid token)
  if (res.status === 401) {
    // Signal session expiry to all subscribers (same-tab fix)
    authManager.signalSessionExpired();
    throw new Error('Unauthorized - please log in again');
  }

  // Throw on other non-2xx errors
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }

  return res;
}

export const dashboardApi = {
  async auth(password: string) {
    const res = await fetch(`${API_BASE}/api/dashboard/auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    return res.json();
  },

  async getVitals() {
    const res = await dashboardFetch('/api/dashboard/vitals');
    return res.json();
  },

  async getDrives() {
    const res = await dashboardFetch('/api/dashboard/drives');
    return res.json();
  },

  async getCosts() {
    const res = await dashboardFetch('/api/dashboard/costs');
    return res.json();
  },

  async getThreads() {
    const res = await dashboardFetch('/api/dashboard/threads');
    return res.json();
  },

  async getPool() {
    const res = await dashboardFetch('/api/dashboard/pool');
    return res.json();
  },

  async getCollection() {
    const res = await dashboardFetch('/api/dashboard/collection');
    return res.json();
  },

  async getTimeline() {
    const res = await dashboardFetch('/api/dashboard/timeline');
    return res.json();
  },

  async getStatus() {
    const res = await dashboardFetch('/api/dashboard/controls/status');
    return res.json();
  },

  async triggerCycle() {
    const res = await dashboardFetch('/api/dashboard/controls/cycle', {
      method: 'POST',
    });
    return res.json();
  },

  async getCycleInterval() {
    const res = await dashboardFetch('/api/dashboard/controls/cycle-interval');
    return res.json();
  },

  async setCycleInterval(intervalSeconds: number) {
    const res = await dashboardFetch('/api/dashboard/controls/cycle-interval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interval_seconds: intervalSeconds }),
    });
    return res.json();
  },

  async getBody() {
    const res = await dashboardFetch('/api/dashboard/body');
    return res.json();
  },

  async getBudget() {
    const res = await dashboardFetch('/api/dashboard/budget');
    return res.json();
  },

  async getBehavioral() {
    const res = await dashboardFetch('/api/dashboard/behavioral');
    return res.json();
  },

  async getContentPool() {
    const res = await dashboardFetch('/api/dashboard/content-pool');
    return res.json();
  },

  async getFeed() {
    const res = await dashboardFetch('/api/dashboard/feed');
    return res.json();
  },

  async getConsumptionHistory() {
    const res = await dashboardFetch('/api/dashboard/consumption-history');
    return res.json();
  },
};
