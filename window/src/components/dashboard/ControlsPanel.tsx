'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';

interface Status {
  heartbeat_active: boolean;
  engagement_status: string;
  shop_status: string;
  active_visitor: string | null;
}

export default function ControlsPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);

  const fetchStatus = async () => {
    try {
      const data = await dashboardApi.getStatus();
      setStatus(data);
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
      // Refresh status after trigger
      await fetchStatus();
    } catch (err) {
      console.error('Failed to trigger cycle:', err);
    } finally {
      setTriggering(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const StatusIndicator = ({ active }: { active: boolean }) => (
    <div className={`h-2 w-2 rounded-full ${active ? 'bg-emerald-500' : 'bg-neutral-600'}`} />
  );

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
              <StatusIndicator active={status.heartbeat_active} />
              <span className="text-xs text-neutral-500 font-mono">
                {status.heartbeat_active ? 'Active' : 'Inactive'}
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
