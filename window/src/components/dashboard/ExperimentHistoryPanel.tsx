'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { ExperimentHistoryData, MetaExperiment, MetaConfidence } from '@/lib/types';

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

function outcomeBg(outcome: string): string {
  switch (outcome) {
    case 'improved': return 'bg-emerald-900/40';
    case 'degraded': return 'bg-red-900/40';
    case 'reverted': return 'bg-red-900/30';
    case 'neutral': return 'bg-neutral-800';
    case 'pending': return 'bg-blue-900/30';
    default: return 'bg-neutral-800';
  }
}

function confidenceColor(c: number): string {
  if (c >= 0.7) return 'text-emerald-400';
  if (c >= 0.4) return 'text-amber-400';
  return 'text-red-400';
}

export default function ExperimentHistoryPanel() {
  const [data, setData] = useState<ExperimentHistoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showConfidence, setShowConfidence] = useState(false);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getExperimentHistory();
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
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Experiments</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Experiments</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  // Outcome summary counts
  const counts: Record<string, number> = {};
  data.experiments.forEach((e: MetaExperiment) => {
    counts[e.outcome] = (counts[e.outcome] || 0) + 1;
  });

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-mono text-neutral-300">Experiments</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-neutral-500">
            {data.experiments.length} total
          </span>
          <button
            onClick={() => setShowConfidence(!showConfidence)}
            className="text-xs font-mono px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded hover:bg-neutral-700 transition-colors"
          >
            {showConfidence ? 'History' : 'Confidence'}
          </button>
        </div>
      </div>

      {/* Outcome summary */}
      <div className="flex gap-3 mb-4 text-xs font-mono">
        {Object.entries(counts).map(([outcome, count]) => (
          <span key={outcome} className={outcomeColor(outcome)}>
            {count} {outcome}
          </span>
        ))}
      </div>

      {showConfidence ? (
        /* Confidence table */
        <div className="space-y-1.5">
          {data.confidence.length === 0 ? (
            <p className="text-xs font-mono text-neutral-600">No confidence data yet</p>
          ) : (
            data.confidence.map((c: MetaConfidence) => (
              <div key={`${c.param_name}-${c.target_metric}`} className="flex items-center justify-between text-xs font-mono">
                <div className="min-w-0">
                  <span className="text-neutral-300 truncate">
                    {c.param_name.split('.').pop()}
                  </span>
                  <span className="text-neutral-600"> &rarr; {c.target_metric}</span>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className={confidenceColor(c.confidence)}>
                    {(c.confidence * 100).toFixed(0)}%
                  </span>
                  <span className="text-neutral-600">
                    {c.attempts} trials
                  </span>
                  <span className="text-neutral-700">
                    {c.improved}W {c.degraded}L {c.neutral}D
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      ) : (
        /* Experiment history */
        <div className="space-y-1.5 max-h-64 overflow-y-auto">
          {data.experiments.slice(0, 20).map((exp: MetaExperiment) => (
            <div key={exp.id} className={`flex items-center justify-between text-xs font-mono px-2 py-1 rounded ${outcomeBg(exp.outcome)}`}>
              <div className="flex items-center gap-2 min-w-0">
                <span className={outcomeColor(exp.outcome)}>
                  {exp.outcome}
                </span>
                <span className="text-neutral-400 truncate">
                  {exp.param_name.split('.').pop()}
                </span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-neutral-500">
                  {exp.old_value.toFixed(2)} &rarr; {exp.new_value.toFixed(2)}
                </span>
                {exp.metric_value_at_change != null && exp.metric_value_after != null && (
                  <span className="text-neutral-600">
                    m: {exp.metric_value_at_change.toFixed(2)} &rarr; {exp.metric_value_after.toFixed(2)}
                  </span>
                )}
                <span className="text-neutral-700">c{exp.cycle_at_change}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
