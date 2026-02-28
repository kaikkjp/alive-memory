'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';

interface Status {
  heartbeat_active: boolean;
  heartbeat_status: 'active' | 'late' | 'inactive';
  last_cycle_ts: string | null;
  seconds_since_last_cycle: number | null;
  expected_interval: number;
  cycle_interval: number;
  engagement_status: string;
  shop_status: string;
  active_visitor: string | null;
}

function formatTimeSince(seconds: number | null): string {
  if (seconds === null) return 'never';
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

const HEARTBEAT_STATUS_CONFIG = {
  active:   { color: 'bg-emerald-500', label: 'Active' },
  late:     { color: 'bg-yellow-500',  label: 'Late' },
  inactive: { color: 'bg-red-500',      label: 'Inactive' },
} as const;

function formatInterval(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  return `${Math.floor(seconds / 3600)}h`;
}

export default function ControlsPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [intervalInput, setIntervalInput] = useState<string>('');
  const [applyingInterval, setApplyingInterval] = useState(false);

  const fetchStatus = async () => {
    try {
      const data = await dashboardApi.getStatus();
      setStatus(data);
      // Sync input with server value on first load or if user hasn't edited
      if (!intervalInput || intervalInput === String(status?.cycle_interval ?? '')) {
        setIntervalInput(String(data.cycle_interval));
      }
    } catch (err) {
      console.error('Failed to fetch status:', err);
    } finally {
      setLoading(false);
    }
  };

  const triggerCycle = async () => {
    setTriggering(true);
    try {
      await dashboardApi.triggerCycle();
      await fetchStatus();
    } catch (err) {
      console.error('Failed to trigger cycle:', err);
    } finally {
      setTriggering(false);
    }
  };

  const applyInterval = async () => {
    const val = parseInt(intervalInput, 10);
    if (isNaN(val) || val < 10 || val > 600) return;
    setApplyingInterval(true);
    try {
      const result = await dashboardApi.setCycleInterval(val);
      setIntervalInput(String(result.interval_seconds));
      await fetchStatus();
    } catch (err) {
      console.error('Failed to set cycle interval:', err);
    } finally {
      setApplyingInterval(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const hbStatus = status
    ? HEARTBEAT_STATUS_CONFIG[status.heartbeat_status] ?? HEARTBEAT_STATUS_CONFIG.inactive
    : HEARTBEAT_STATUS_CONFIG.inactive;

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Controls</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Controls</h2>
        <p className="text-sm text-red-400 font-mono">Error loading status</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Controls</h2>

      <div className="space-y-4">
        {/* Status indicators */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-neutral-400 font-mono">Heartbeat</span>
            <div className="flex items-center gap-2">
              <div className={`h-2 w-2 rounded-full ${hbStatus.color}`} />
              <span className="text-xs text-neutral-500 font-mono">
                {hbStatus.label}
              </span>
              <span className="text-xs text-neutral-600 font-mono">
                {formatTimeSince(status.seconds_since_last_cycle)}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-sm text-neutral-400 font-mono">Shop</span>
            <span className="text-xs text-neutral-300 font-mono uppercase">
              {status.shop_status}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-sm text-neutral-400 font-mono">Engagement</span>
            <span className="text-xs text-neutral-300 font-mono uppercase">
              {status.engagement_status}
            </span>
          </div>

          {status.active_visitor && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-neutral-400 font-mono">Visitor</span>
              <span className="text-xs text-blue-400 font-mono">
                {status.active_visitor}
              </span>
            </div>
          )}
        </div>

        {/* Cycle interval */}
        <div className="pt-4 border-t border-neutral-700">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-neutral-400 font-mono">Cycle Interval</span>
            <span className="text-xs text-neutral-500 font-mono">
              Every {formatInterval(status.cycle_interval)}
            </span>
          </div>
          <div className="flex gap-2">
            <input
              type="number"
              min={10}
              max={600}
              value={intervalInput}
              onChange={(e) => setIntervalInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') applyInterval(); }}
              className="flex-1 px-3 py-1.5 bg-neutral-800 border border-neutral-600 rounded text-neutral-200 font-mono text-sm focus:outline-none focus:border-purple-500"
            />
            <button
              onClick={applyInterval}
              disabled={applyingInterval || intervalInput === String(status.cycle_interval)}
              className="px-3 py-1.5 bg-neutral-700 hover:bg-neutral-600 disabled:bg-neutral-800 disabled:text-neutral-600 text-neutral-200 font-mono text-xs rounded transition-colors"
            >
              {applyingInterval ? '...' : 'Apply'}
            </button>
          </div>
          <p className="text-xs text-neutral-500 font-mono mt-1">
            10s – 600s. Takes effect next cycle.
          </p>
        </div>

        {/* Manual controls */}
        <div className="pt-4 border-t border-neutral-700">
          <button
            onClick={triggerCycle}
            disabled={triggering}
            className="w-full px-4 py-2 bg-purple-700 hover:bg-purple-600 disabled:bg-neutral-800 text-neutral-100 font-mono text-sm rounded transition-colors"
          >
            {triggering ? 'Triggering...' : 'Trigger Cycle'}
          </button>
          <p className="text-xs text-neutral-500 font-mono mt-2">
            Manually trigger an autonomous cycle
          </p>
        </div>
      </div>
    </div>
  );
}
