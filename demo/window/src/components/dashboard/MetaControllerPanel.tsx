'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { MetaControllerData } from '@/lib/types';

/**
 * Known metric normalization divisors.
 *
 * Backend sends raw metric values alongside normalized 0–1 target bounds.
 * The backend comparison is currently unit-inconsistent (raw vs normalized),
 * so the frontend normalizes the current value for display.
 */
const METRIC_NORMALIZERS: Record<string, number> = {
  initiative_rate: 100.0,   // raw 0–100 (percent) → 0.0–1.0
  emotional_range: 125.0,   // raw 0–125 (5^3 bins) → 0.0–1.0
};

function normalizeCurrentValue(metricName: string, raw: number | null): number | null {
  if (raw == null) return null;
  const divisor = METRIC_NORMALIZERS[metricName];
  return divisor ? raw / divisor : raw;
}

function computeStatus(
  normalizedCurrent: number | null,
  min: number | null,
  max: number | null,
): string {
  if (normalizedCurrent == null) return 'unknown';
  if (min != null && normalizedCurrent < min) return 'low';
  if (max != null && normalizedCurrent > max) return 'high';
  return 'ok';
}

function statusColor(status: string): string {
  switch (status) {
    case 'ok': return 'text-emerald-400';
    case 'low': return 'text-amber-400';
    case 'high': return 'text-red-400';
    default: return 'text-neutral-500';
  }
}

function statusDot(status: string): string {
  switch (status) {
    case 'ok': return 'bg-emerald-500';
    case 'low': return 'bg-amber-500';
    case 'high': return 'bg-red-500';
    default: return 'bg-neutral-600';
  }
}

function outcomeColor(outcome: string): string {
  switch (outcome) {
    case 'improved': return 'text-emerald-400';
    case 'degraded': return 'text-red-400';
    case 'reverted': return 'text-red-300';
    case 'neutral': return 'text-neutral-400';
    case 'pending': return 'text-blue-400';
    default: return 'text-neutral-500';
  }
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function MetaControllerPanel() {
  const [data, setData] = useState<MetaControllerData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getMetaController();
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Meta-Controller</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Meta-Controller</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  const targetEntries = Object.entries(data.targets);

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-mono text-neutral-300">Meta-Controller</h2>
        <div className="flex items-center gap-2">
          {data.pending_count > 0 && (
            <span className="text-xs font-mono px-1.5 py-0.5 bg-blue-900 text-blue-400 rounded">
              {data.pending_count} pending
            </span>
          )}
          <span className={`text-xs font-mono px-2 py-0.5 rounded ${
            data.enabled ? 'bg-emerald-900 text-emerald-400' : 'bg-neutral-800 text-neutral-500'
          }`}>
            {data.enabled ? 'Active' : 'Disabled'}
          </span>
        </div>
      </div>

      {/* Targets */}
      {targetEntries.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Targets</h3>
          <div className="space-y-2">
            {targetEntries.map(([name, target]) => {
              // Normalize raw current value to match the 0–1 target bounds
              const normalized = normalizeCurrentValue(target.metric, target.current);
              const correctedStatus = computeStatus(normalized, target.min, target.max);
              return (
                <div key={name} className="flex items-center justify-between text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <div className={`w-1.5 h-1.5 rounded-full ${statusDot(correctedStatus)}`} />
                    <span className="text-neutral-300">{name}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-neutral-600">
                      {target.min != null ? target.min.toFixed(2) : '?'}
                      {' \u2013 '}
                      {target.max != null ? target.max.toFixed(2) : '?'}
                    </span>
                    <span className={statusColor(correctedStatus)}>
                      {normalized != null ? normalized.toFixed(3) : 'n/a'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Recent adjustments */}
      {data.recent_adjustments.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Recent Adjustments</h3>
          <div className="space-y-1.5">
            {data.recent_adjustments.slice(0, 5).map((exp) => (
              <div key={exp.id} className="flex items-center justify-between text-xs font-mono">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={outcomeColor(exp.outcome)}>{exp.outcome}</span>
                  <span className="text-neutral-400 truncate">
                    {exp.param_name.split('.').pop()}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-neutral-600 shrink-0">
                  <span>{exp.old_value.toFixed(2)} &rarr; {exp.new_value.toFixed(2)}</span>
                  <span>{timeAgo(exp.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Config summary */}
      <div className="border-t border-neutral-700 pt-3">
        <div className="flex gap-4 text-xs font-mono text-neutral-600">
          <span>window: {data.config.evaluation_window}c</span>
          <span>cooldown: {data.config.cooldown_cycles}c</span>
          <span>max/sleep: {data.config.max_adjustments_per_sleep}</span>
        </div>
      </div>
    </div>
  );
}
