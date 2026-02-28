'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { DriftData } from '@/lib/types';

function levelColor(level: string): string {
  switch (level) {
    case 'significant': return 'bg-red-500';
    case 'notable': return 'bg-amber-500';
    default: return 'bg-emerald-500';
  }
}

function levelLabel(level: string): string {
  switch (level) {
    case 'significant': return 'Significant';
    case 'notable': return 'Notable';
    default: return 'Stable';
  }
}

function levelTextColor(level: string): string {
  switch (level) {
    case 'significant': return 'text-red-400';
    case 'notable': return 'text-amber-400';
    default: return 'text-emerald-400';
  }
}

const METRIC_LABELS: Record<string, string> = {
  action_frequency: 'Actions',
  drive_response: 'Drives',
  conversation_style: 'Speech',
  sleep_wake_rhythm: 'Rhythm',
};

export default function DriftPanel() {
  const [drift, setDrift] = useState<DriftData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchDrift = async () => {
    try {
      const data = await dashboardApi.getDrift();
      setDrift(data);
    } catch (err) {
      console.error('Failed to fetch drift:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDrift();
    const interval = setInterval(fetchDrift, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Drift</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!drift) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Drift</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  const compositePercent = Math.round(drift.composite * 100);

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-mono text-neutral-300">Drift</h2>
        <span className={`text-xs font-mono ${levelTextColor(drift.level)}`}>
          {levelLabel(drift.level)}
        </span>
      </div>

      {/* Composite score bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-neutral-400 font-mono mb-1">
          <span>Composite</span>
          <span>{compositePercent}%</span>
        </div>
        <div className="h-3 bg-neutral-800 rounded overflow-hidden">
          <div
            className={`h-full ${levelColor(drift.level)} transition-all duration-500`}
            style={{ width: `${compositePercent}%` }}
          />
        </div>
      </div>

      {/* Per-metric breakdown */}
      <div className="space-y-2 mb-4">
        {Object.entries(drift.metrics).map(([key, value]) => {
          const pct = Math.round(value * 100);
          return (
            <div key={key}>
              <div className="flex justify-between text-xs text-neutral-500 font-mono mb-0.5">
                <span>{METRIC_LABELS[key] || key}</span>
                <span>{pct}%</span>
              </div>
              <div className="h-1.5 bg-neutral-800 rounded overflow-hidden">
                <div
                  className="h-full bg-neutral-500 transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary + baseline info */}
      <div className="border-t border-neutral-700 pt-3 space-y-2">
        {drift.summary && (
          <p className="text-xs font-mono text-neutral-300 italic">
            &ldquo;{drift.summary}&rdquo;
          </p>
        )}
        <p className="text-xs font-mono text-neutral-600">
          Baseline: {drift.baseline_cycles} cycles
          {!drift.baseline_mature && ' (warming up)'}
        </p>
      </div>
    </div>
  );
}
