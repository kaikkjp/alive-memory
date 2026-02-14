'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import { authManager } from '@/lib/auth-manager';
import VitalsPanel from '@/components/dashboard/VitalsPanel';
import DrivesPanel from '@/components/dashboard/DrivesPanel';
import CostsPanel from '@/components/dashboard/CostsPanel';
import ThreadsPanel from '@/components/dashboard/ThreadsPanel';
import PoolPanel from '@/components/dashboard/PoolPanel';
import CollectionPanel from '@/components/dashboard/CollectionPanel';
import TimelinePanel from '@/components/dashboard/TimelinePanel';
import ControlsPanel from '@/components/dashboard/ControlsPanel';

export default function DashboardPage() {
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Check if already authenticated (token in sessionStorage)
    if (authManager.isAuthenticated()) {
      setAuthenticated(true);
    }
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const data = await dashboardApi.auth(password);

      if (data.authenticated && data.token) {
        authManager.setToken(data.token);
        setAuthenticated(true);
      } else {
        setError('Invalid password');
      }
    } catch (err) {
      setError('Cannot connect to server');
    } finally {
      setLoading(false);
    }
  };

  if (!authenticated) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center p-4">
        <div className="w-full max-w-md">
          <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-8">
            <h1 className="text-2xl font-mono text-neutral-100 mb-6">
              Operator Dashboard
            </h1>
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-sm font-mono text-neutral-400 mb-2">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-4 py-2 bg-black border border-neutral-700 rounded text-neutral-100 font-mono focus:outline-none focus:border-neutral-500"
                  placeholder="Enter dashboard password"
                  disabled={loading}
                />
              </div>
              {error && (
                <p className="text-sm text-red-400 font-mono">{error}</p>
              )}
              <button
                type="submit"
                disabled={loading}
                className="w-full px-4 py-2 bg-neutral-700 hover:bg-neutral-600 disabled:bg-neutral-800 text-neutral-100 font-mono rounded transition-colors"
              >
                {loading ? 'Authenticating...' : 'Enter'}
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-neutral-100 p-6">
      <div className="max-w-7xl mx-auto">
        <header className="mb-8">
          <h1 className="text-3xl font-mono text-neutral-100">
            Shopkeeper Dashboard
          </h1>
          <p className="text-sm font-mono text-neutral-400 mt-2">
            Live operator view · Real-time monitoring
          </p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <VitalsPanel />
          <DrivesPanel />
          <CostsPanel />
          <ThreadsPanel />
          <PoolPanel />
          <CollectionPanel />
          <TimelinePanel />
          <ControlsPanel />
        </div>
      </div>
    </div>
  );
}
