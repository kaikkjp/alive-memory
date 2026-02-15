'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { BodyPanelData } from '@/lib/types';

function StatusDot({ enabled, ready, coolingUntil }: {
  enabled: boolean;
  ready: boolean;
  coolingUntil: string | null;
}) {
  if (!enabled) return <span className="inline-block w-2 h-2 rounded-full bg-neutral-600" title="Disabled" />;
  if (!ready && coolingUntil) {
    const remaining = Math.max(0, Math.round((new Date(coolingUntil).getTime() - Date.now()) / 1000));
    return <span className="inline-block w-2 h-2 rounded-full bg-yellow-500" title={`Cooling: ${remaining}s`} />;
  }
  return <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" title="Ready" />;
}

export default function BodyPanel() {
  const [data, setData] = useState<BodyPanelData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getBody();
      setData(result);
    } catch (err) {
      console.error('[BodyPanel] Failed to fetch:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Body</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Body</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  const energyPct = Math.round((data.energy.spent_today / data.energy.budget) * 100);
  const enabledCaps = data.capabilities.filter(c => c.enabled);

  // Build a lookup for today's action counts
  const countMap: Record<string, number> = {};
  for (const a of data.actions_today) {
    countMap[a.type] = a.count;
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Body</h2>

      {/* Energy bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-neutral-400 font-mono mb-1">
          <span>Energy spent</span>
          <span>{data.energy.spent_today.toFixed(2)} / {data.energy.budget.toFixed(1)} ({energyPct}%)</span>
        </div>
        <div className="h-2 bg-neutral-800 rounded overflow-hidden">
          <div
            className="h-full bg-amber-500 transition-all duration-500"
            style={{ width: `${Math.min(energyPct, 100)}%` }}
          />
        </div>
      </div>

      {/* Capability grid */}
      <div className="mb-4">
        <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Capabilities</h3>
        <div className="space-y-1">
          {enabledCaps.map((cap) => (
            <div key={cap.action} className="flex items-center justify-between text-xs font-mono">
              <div className="flex items-center gap-2">
                <StatusDot enabled={cap.enabled} ready={cap.ready} coolingUntil={cap.cooling_until} />
                <span className="text-neutral-300">{cap.action}</span>
              </div>
              <div className="flex items-center gap-3 text-neutral-500">
                <span>{cap.energy_cost.toFixed(2)}e</span>
                <span className="w-8 text-right">{countMap[cap.action] || 0}x</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Actions today */}
      {data.actions_today.length > 0 && (
        <div>
          <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Actions Today</h3>
          <div className="space-y-1">
            {data.actions_today.map((a) => (
              <div key={a.type} className="flex items-center justify-between text-xs font-mono">
                <span className="text-neutral-300">{a.type}</span>
                <div className="flex items-center gap-3 text-neutral-500">
                  <span>{a.count}x</span>
                  <span>{a.total_energy.toFixed(2)}e</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
