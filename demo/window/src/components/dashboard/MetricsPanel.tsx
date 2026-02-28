'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { MetricsData, MetricResult, MetricTrendPoint } from '@/lib/types';

/**
 * Per-metric normalization.
 *
 * Backend metric values use different scales:
 *   uptime        → raw cycle count (e.g. 5000)
 *   initiative_rate → 0–100 (percentage)
 *   emotional_range → 0–125 (unique mood-state bins out of 5^3)
 *
 * Each entry defines how to convert the raw value into a 0–1 fraction
 * for bar display, what label to show, and a color threshold override.
 */
interface MetricNorm {
  /** Human label */
  label: string;
  /** Convert raw value → 0..1 for bar width */
  normalize: (value: number, details: Record<string, unknown>) => number;
  /** Format the display value shown next to sparkline */
  format: (value: number, details: Record<string, unknown>) => string;
  /** true = this metric has no meaningful 0..1 bar (show value only) */
  noBar?: boolean;
}

const METRIC_NORMS: Record<string, MetricNorm> = {
  uptime: {
    label: 'Uptime',
    normalize: () => 1, // always full — uptime is a count, not a fraction
    format: (v, d) => {
      const days = (d.days_alive as number) ?? 0;
      return `${Math.round(v).toLocaleString()} cycles (${days}d)`;
    },
    noBar: true,
  },
  initiative_rate: {
    label: 'Initiative',
    normalize: (v) => Math.min(v / 100, 1), // 0–100% → 0–1
    format: (v) => `${v.toFixed(1)}%`,
  },
  emotional_range: {
    label: 'Emo. Range',
    normalize: (v) => Math.min(v / 125, 1), // 0–125 bins → 0–1
    format: (v, d) => {
      const total = (d.total_possible as number) ?? 125;
      return `${Math.round(v)}/${total}`;
    },
  },
};

/**
 * Fallback for metrics without an explicit METRIC_NORMS entry.
 * Uses the display string as primary; shows raw value (no bar) to
 * avoid misleading 0–1 assumptions on unknown-scale metrics.
 */
const DEFAULT_NORM: MetricNorm = {
  label: '',
  normalize: () => 0,
  format: (v) => v.toLocaleString(),
  noBar: true,
};

function barColor(frac: number): string {
  if (frac >= 0.7) return 'bg-emerald-500';
  if (frac >= 0.4) return 'bg-amber-500';
  return 'bg-red-500';
}

/**
 * Unicode block sparkline from trend points.
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
  // Use relative threshold for trend detection (1% of first value, min 0.5)
  const threshold = Math.max(Math.abs(first) * 0.01, 0.5);
  if (Math.abs(delta) < threshold) return { label: '\u2192', color: 'text-neutral-500' };
  if (delta > 0) return { label: '\u2191', color: 'text-emerald-400' };
  return { label: '\u2193', color: 'text-red-400' };
}

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

      <div className="space-y-3">
        {data.snapshot.metrics.map((m: MetricResult) => {
          const norm = METRIC_NORMS[m.name] || DEFAULT_NORM;
          const details = m.details || {};
          const frac = norm.normalize(m.value, details);
          const formatted = norm.format(m.value, details);
          const trend = data.trends[m.name];
          const dir = trendDirection(trend);
          const spark = sparkline(trend);

          return (
            <div key={m.name}>
              <div className="flex items-center justify-between text-xs font-mono mb-1">
                <span className="text-neutral-400">
                  {norm.label || m.name}
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
                  <span className="text-neutral-300">
                    {formatted}
                  </span>
                </div>
              </div>
              {!norm.noBar && (
                <div className="h-2 bg-neutral-800 rounded overflow-hidden">
                  <div
                    className={`h-full ${barColor(frac)} transition-all duration-500`}
                    style={{ width: `${Math.round(frac * 100)}%` }}
                  />
                </div>
              )}
              {m.display && (
                <p className="text-[10px] font-mono text-neutral-600 mt-0.5">{m.display}</p>
              )}
            </div>
          );
        })}
      </div>

      <div className="border-t border-neutral-700 pt-3 mt-4">
        <p className="text-xs font-mono text-neutral-600">
          Last snapshot: {new Date(data.snapshot.timestamp).toLocaleTimeString()}
        </p>
      </div>
    </div>
  );
}
