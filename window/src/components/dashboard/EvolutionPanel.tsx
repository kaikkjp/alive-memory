'use client';

import { useState, useEffect } from 'react';
import { dashboardFetch } from '@/lib/dashboard-api';

interface EvolutionData {
  enabled: boolean;
  config: {
    conscious_protection_cycles: number;
    baseline_shift_window: number;
    organic_growth_threshold: number;
    max_updates_per_sleep: number;
    protected_traits: string[];
  };
  conscious_protections: Array<{
    param: string;
    new_value: number;
    modified_at: string;
  }>;
  recent_decisions: Array<{
    type: string;
    payload: Record<string, unknown>;
    ts: string;
  }>;
  current_drift: Array<{
    param_name: string;
    baseline_value: number;
    current_value: number;
    drift_magnitude: number;
  }>;
  cycle_count: number;
}

function decisionColor(type: string): string {
  switch (type) {
    case 'accepted': return 'text-emerald-400';
    case 'corrected': return 'text-amber-400';
    case 'deferred': return 'text-neutral-500';
    default: return 'text-neutral-400';
  }
}

function decisionIcon(type: string): string {
  switch (type) {
    case 'accepted': return '\u2713';  // checkmark
    case 'corrected': return '\u21BA'; // counterclockwise arrow
    case 'deferred': return '\u2014';  // em dash
    default: return '?';
  }
}

export default function EvolutionPanel() {
  const [data, setData] = useState<EvolutionData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchEvolution = async () => {
    try {
      const res = await dashboardFetch('/api/dashboard/identity-evolution');
      setData(await res.json());
    } catch {
      // dashboardFetch handles 401/session-expiry; swallow other errors
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvolution();
    const interval = setInterval(fetchEvolution, 15000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Identity Evolution</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Identity Evolution</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-mono text-neutral-300">Identity Evolution</h2>
        <span className={`text-xs font-mono px-2 py-0.5 rounded ${
          data.enabled ? 'bg-emerald-900 text-emerald-400' : 'bg-neutral-800 text-neutral-500'
        }`}>
          {data.enabled ? 'Active' : 'Disabled'}
        </span>
      </div>

      {/* Conscious protections */}
      {data.conscious_protections.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Conscious Protections</h3>
          <div className="space-y-1">
            {data.conscious_protections.map((p, i) => (
              <div key={i} className="flex justify-between text-xs font-mono">
                <span className="text-blue-400">{p.param.split('.').pop()}</span>
                <span className="text-neutral-500">{p.new_value.toFixed(3)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Current drift */}
      {data.current_drift.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Drifted Parameters</h3>
          <div className="space-y-1">
            {data.current_drift.map((d, i) => (
              <div key={i} className="flex justify-between text-xs font-mono">
                <span className="text-neutral-300">{d.param_name.split('.').pop()}</span>
                <span className="text-amber-400">{d.drift_magnitude.toFixed(3)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent decisions */}
      {data.recent_decisions.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Recent Decisions</h3>
          <div className="space-y-1">
            {data.recent_decisions.slice(0, 5).map((d, i) => (
              <div key={i} className="flex items-center gap-2 text-xs font-mono">
                <span className={decisionColor(d.type)}>{decisionIcon(d.type)}</span>
                <span className={decisionColor(d.type)}>{d.type}</span>
                {d.payload && typeof d.payload === 'object' && 'param' in d.payload && (
                  <span className="text-neutral-500">{String(d.payload.param).split('.').pop()}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Guard rails */}
      <div className="border-t border-neutral-700 pt-3">
        <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Protected Traits</h3>
        <div className="flex flex-wrap gap-1">
          {data.config.protected_traits.map((trait) => (
            <span key={trait} className="text-xs font-mono px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded">
              {trait}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
