'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { BehavioralPanelData } from '@/lib/types';

// Default/dominant state — badges for these are suppressed
const DEFAULTS: Record<string, string> = {
  energy: 'high',
  mood: 'positive',
  mode: 'idle',
  visitor: 'false',
};

const BADGE_COLORS: Record<string, string> = {
  morning:   'bg-amber-800 text-amber-200',
  afternoon: 'bg-sky-800 text-sky-200',
  evening:   'bg-indigo-800 text-indigo-200',
  night:     'bg-neutral-700 text-neutral-300',
  'energy:low':  'bg-red-900 text-red-300',
  'energy:mid':  'bg-amber-900 text-amber-300',
  'mood:negative': 'bg-red-900 text-red-300',
  'mood:neutral':  'bg-neutral-700 text-neutral-300',
  visitor:   'bg-emerald-900 text-emerald-300',
  engaged:   'bg-purple-900 text-purple-300',
  reading:   'bg-blue-900 text-blue-300',
  thread:    'bg-purple-900 text-purple-300',
  sleep:     'bg-neutral-700 text-neutral-300',
};

function parseBadges(raw: string): { label: string; color: string }[] {
  if (!raw) return [];
  const badges: { label: string; color: string }[] = [];
  for (const part of raw.split('|')) {
    const [key, val] = part.split(':');
    if (!key || !val) continue;
    // Skip defaults
    if (DEFAULTS[key] === val) continue;
    // Time band always shows
    if (key === 'time') {
      badges.push({ label: val, color: BADGE_COLORS[val] || 'bg-neutral-700 text-neutral-300' });
    } else if (key === 'visitor' && val === 'true') {
      badges.push({ label: 'visitor', color: BADGE_COLORS.visitor });
    } else if (key === 'energy') {
      badges.push({ label: `${key}:${val}`, color: BADGE_COLORS[`energy:${val}`] || 'bg-neutral-700 text-neutral-300' });
    } else if (key === 'mood') {
      badges.push({ label: `${key}:${val}`, color: BADGE_COLORS[`mood:${val}`] || 'bg-neutral-700 text-neutral-300' });
    } else if (key === 'mode') {
      badges.push({ label: val, color: BADGE_COLORS[val] || 'bg-neutral-700 text-neutral-300' });
    }
  }
  return badges;
}

function ContextBadges({ raw }: { raw: string }) {
  const badges = parseBadges(raw);
  if (badges.length === 0) return null;
  return (
    <span className="inline-flex gap-1 ml-1.5" title={raw}>
      {badges.map((b, i) => (
        <span key={i} className={`px-1 py-0 rounded text-[10px] leading-4 ${b.color}`}>
          {b.label}
        </span>
      ))}
    </span>
  );
}

function StrengthBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.6 ? 'bg-emerald-500' : value >= 0.3 ? 'bg-amber-500' : 'bg-neutral-500';
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-neutral-800 rounded overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-neutral-500 font-mono w-8">{pct}%</span>
    </div>
  );
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function BehavioralPanel() {
  const [data, setData] = useState<BehavioralPanelData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getBehavioral();
      setData(result);
    } catch (err) {
      console.error('[BehavioralPanel] Failed to fetch:', err);
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
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Behavioral</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Behavioral</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Behavioral</h2>

      {/* Cost savings */}
      <div className="mb-4 px-3 py-2 bg-neutral-800 rounded">
        <span className="text-xs font-mono text-neutral-400">Cortex calls saved by habits: </span>
        <span className="text-sm font-mono text-emerald-400">{data.habit_skips_today}</span>
      </div>

      {/* Habits */}
      <div className="mb-4">
        <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Top Habits</h3>
        {data.habits.length === 0 ? (
          <p className="text-xs text-neutral-600 font-mono">No habits formed yet</p>
        ) : (
          <div className="space-y-2">
            {data.habits.map((h, i) => (
              <div key={i} className="flex items-center justify-between text-xs font-mono gap-2" title={h.trigger_context}>
                <div className="flex items-center flex-1 min-w-0">
                  <span className="text-neutral-300 shrink-0">{h.action}</span>
                  <ContextBadges raw={h.trigger_context} />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <StrengthBar value={h.strength} />
                  <span className="text-neutral-500 w-8 text-right">{h.fire_count}x</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Inhibitions */}
      <div className="mb-4">
        <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Active Inhibitions</h3>
        {data.inhibitions.length === 0 ? (
          <p className="text-xs text-neutral-600 font-mono">No inhibitions active</p>
        ) : (
          <div className="space-y-2">
            {data.inhibitions.map((inh, i) => (
              <div key={i} className="flex items-center justify-between text-xs font-mono">
                <div className="flex-1 min-w-0">
                  <span className="text-red-400">{inh.action}</span>
                  <span className="text-neutral-600 ml-2 truncate">{inh.context}</span>
                </div>
                <div className="flex items-center gap-2 ml-2">
                  <StrengthBar value={inh.strength} />
                  <span className="text-neutral-500 w-8 text-right">{inh.trigger_count}x</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Suppressions — "She almost..." feed */}
      <div>
        <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">She almost...</h3>
        {data.suppressions.length === 0 ? (
          <p className="text-xs text-neutral-600 font-mono">No recent suppressions</p>
        ) : (
          <div className="space-y-2">
            {data.suppressions.map((s, i) => (
              <div key={i} className="text-xs font-mono border-l-2 border-neutral-700 pl-2">
                <div className="flex items-center justify-between">
                  <span className="text-amber-400">{s.action}</span>
                  <span className="text-neutral-600">{timeAgo(s.timestamp)}</span>
                </div>
                <div className="text-neutral-500 mt-0.5">
                  impulse {(s.impulse * 100).toFixed(0)}% — {s.reason || 'suppressed'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
