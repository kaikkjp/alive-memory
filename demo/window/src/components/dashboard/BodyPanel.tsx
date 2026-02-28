'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { BodyPanelData, BudgetData } from '@/lib/types';

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

function budgetBarColor(remaining: number, budget: number): string {
  if (budget <= 0) return 'bg-red-500';
  const pct = remaining / budget;
  if (pct > 0.5) return 'bg-emerald-500';
  if (pct > 0.2) return 'bg-yellow-500';
  return 'bg-red-500';
}

export default function BodyPanel() {
  const [data, setData] = useState<BodyPanelData | null>(null);
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const [bodyResult, budgetResult] = await Promise.all([
        dashboardApi.getBody(),
        dashboardApi.getBudget(),
      ]);
      setData(bodyResult);
      setBudget(budgetResult);
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

  const enabledCaps = data.capabilities.filter(c => c.enabled);

  // Build a lookup for today's action counts
  const countMap: Record<string, number> = {};
  for (const a of data.actions_today) {
    countMap[a.type] = a.count;
  }

  const budgetPct = budget && budget.budget > 0
    ? Math.round((budget.remaining / budget.budget) * 100)
    : 0;
  const budgetExhausted = budget ? budget.remaining <= 0 : false;

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Body</h2>

      {/* Budget bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-neutral-400 font-mono mb-1">
          <span>{budgetExhausted ? 'Resting — budget spent' : 'Budget remaining'}</span>
          {budget && (
            <span>${budget.remaining.toFixed(2)} / ${budget.budget.toFixed(2)}</span>
          )}
        </div>
        <div className="h-2 bg-neutral-800 rounded overflow-hidden">
          <div
            className={`h-full ${budget ? budgetBarColor(budget.remaining, budget.budget) : 'bg-neutral-600'} transition-all duration-500`}
            style={{ width: `${Math.min(budgetPct, 100)}%` }}
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
              <span className="inline-block w-8 text-right text-neutral-500">{countMap[cap.action] || 0}x</span>
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
