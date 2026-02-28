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
import BodyPanel from '@/components/dashboard/BodyPanel';
import BehavioralPanel from '@/components/dashboard/BehavioralPanel';
import ContentPoolPanel from '@/components/dashboard/ContentPoolPanel';
import FeedPanel from '@/components/dashboard/FeedPanel';
import ConsumptionHistoryPanel from '@/components/dashboard/ConsumptionHistoryPanel';
import ParametersPanel from '@/components/dashboard/ParametersPanel';
import XDraftsPanel from '@/components/dashboard/XDraftsPanel';
import ActionsPanel from '@/components/dashboard/ActionsPanel';
import BudgetPanel from '@/components/dashboard/BudgetPanel';
import DriftPanel from '@/components/dashboard/DriftPanel';
import EvolutionPanel from '@/components/dashboard/EvolutionPanel';
import ExternalActionsPanel from '@/components/dashboard/ExternalActionsPanel';
import MetaControllerPanel from '@/components/dashboard/MetaControllerPanel';
import ExperimentHistoryPanel from '@/components/dashboard/ExperimentHistoryPanel';
import MetricsPanel from '@/components/dashboard/MetricsPanel';

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
    <div className="min-h-screen bg-black text-neutral-100 p-4 md:p-6 pb-16">
      <div className="max-w-7xl mx-auto space-y-10">
        <header className="mb-2">
          <h1 className="text-2xl font-mono text-neutral-100">
            Shopkeeper Dashboard
          </h1>
          <p className="text-xs font-mono text-neutral-500 mt-1">
            Live operator view
          </p>
        </header>

        {/* ── Status ── */}
        <section>
          <h2 className="text-xs font-mono text-neutral-500 uppercase tracking-widest mb-3 border-b border-neutral-800 pb-2">
            Status
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <VitalsPanel />
            <DrivesPanel />
            <BodyPanel />
          </div>
        </section>

        {/* ── Behavior ── */}
        <section>
          <h2 className="text-xs font-mono text-neutral-500 uppercase tracking-widest mb-3 border-b border-neutral-800 pb-2">
            Behavior
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <BehavioralPanel />
            <CostsPanel />
            <BudgetPanel />
            <DriftPanel />
            <EvolutionPanel />
          </div>
        </section>

        {/* ── Social ── */}
        <section>
          <h2 className="text-xs font-mono text-neutral-500 uppercase tracking-widest mb-3 border-b border-neutral-800 pb-2">
            Social
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <ExternalActionsPanel />
            <XDraftsPanel />
            <ThreadsPanel />
          </div>
        </section>

        {/* ── Content ── */}
        <section>
          <h2 className="text-xs font-mono text-neutral-500 uppercase tracking-widest mb-3 border-b border-neutral-800 pb-2">
            Content
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <PoolPanel />
            <CollectionPanel />
            <ContentPoolPanel />
            <FeedPanel />
            <ConsumptionHistoryPanel />
          </div>
        </section>

        {/* ── System ── */}
        <section>
          <h2 className="text-xs font-mono text-neutral-500 uppercase tracking-widest mb-3 border-b border-neutral-800 pb-2">
            System
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <MetricsPanel />
            <MetaControllerPanel />
            <ExperimentHistoryPanel />
            <ParametersPanel />
            <ActionsPanel />
            <TimelinePanel />
            <ControlsPanel />
          </div>
        </section>
      </div>
    </div>
  );
}
