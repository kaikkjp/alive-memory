'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { MetricsData, MetricResult, MetricTrendPoint } from '@/lib/types';

function metricColor(value: number): string {
  if (value >= 0.7) return 'text-emerald-400';
  if (value >= 0.4) return 'text-amber-400';
  return 'text-red-400';
}

function metricBarColor(value: number): string {
  if (value >= 0.7) return 'bg-emerald-500';
  if (value >= 0.4) return 'bg-amber-500';
  return 'bg-red-500';
}

/**
 * Simple ASCII-style sparkline from trend data.
 * Returns a string of block characters showing the trend.
 */
function sparkline(points: MetricTrendPoint[], width: number = 14): string {
  if (!points || points.length === 0) return '';
  const values = points.slice(-width).map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 0.01;
  const blocks = ['\u2581', '\u2582', '\u2583', '\u2584', '\u2585', '\u2586', '\u2587', '\u2588'];
  return values.map((v) => {
    const idx = Math.min(Math.floor(((v - min) / range) * 7), 7);
    return blocks[idx];
  }).join('');
}

function trendDirection(points: MetricTrendPoint[]): { label: string; color: string } {
  if (!points || points.length < 2) return { label: '', color: 'text-neutral-600' };
  const recent = points.slice(-7);
  const first = recent[0].value;
  const last = recent[recent.length - 1].value;
  const delta = last - first;
  if (Math.abs(delta) < 0.01) return { label: '\u2192', color: 'text-neutral-500' }; // arrow right
  if (delta > 0) return { label: '\u2191', color: 'text-emerald-400' }; // arrow up
  return { label: '\u2193', color: 'text-red-400' }; // arrow down
}

const METRIC_LABELS: Record<string, string> = {
  uptime: 'Uptime',
  initiative_rate: 'Initiative',
  emotional_range: 'Emo. Range',
  vocabulary_diversity: 'Vocab',
  memory_utilization: 'Memory',
  social_responsiveness: 'Social',
  action_diversity: 'Actions',
};

export default function MetricsPanel() {
  const [data, setData] = useState<MetricsData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getMetrics();
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
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Liveness Metrics</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Liveness Metrics</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-mono text-neutral-300">Liveness Metrics</h2>
        <span className="text-xs font-mono text-neutral-600">
          {data.snapshot.period}
        </span>
      </div>

      {/* Metric bars */}
      <div className="space-y-3">
        {data.snapshot.metrics.map((m: MetricResult) => {
          const pct = Math.round(m.value * 100);
          const trend = data.trends[m.name];
          const dir = trendDirection(trend);
          const spark = sparkline(trend);

          return (
            <div key={m.name}>
              <div className="flex items-center justify-between text-xs font-mono mb-1">
                <span className="text-neutral-400">
                  {METRIC_LABELS[m.name] || m.name}
                </span>
                <div className="flex items-center gap-2">
                  {spark && (
                    <span className="text-neutral-600 text-[10px] tracking-tighter">
                      {spark}
                    </span>
                  )}
                  {dir.label && (
                    <span className={dir.color}>{dir.label}</span>
                  )}
                  <span className={metricColor(m.value)}>
                    {pct}%
                  </span>
                </div>
              </div>
              <div className="h-2 bg-neutral-800 rounded overflow-hidden">
                <div
                  className={`h-full ${metricBarColor(m.value)} transition-all duration-500`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {m.display && (
                <p className="text-[10px] font-mono text-neutral-600 mt-0.5">{m.display}</p>
              )}
            </div>
          );
        })}
      </div>

      {/* Timestamp */}
      <div className="border-t border-neutral-700 pt-3 mt-4">
        <p className="text-xs font-mono text-neutral-600">
          Last snapshot: {new Date(data.snapshot.timestamp).toLocaleTimeString()}
        </p>
      </div>
    </div>
  );
}
