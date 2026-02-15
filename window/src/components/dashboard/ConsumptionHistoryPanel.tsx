'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { ConsumptionHistoryData } from '@/lib/types';

const SOURCE_TYPE_LABELS: Record<string, { icon: string; label: string }> = {
  rss_headline: { icon: '📰', label: 'RSS' },
  url: { icon: '🔗', label: 'URL' },
  text: { icon: '📝', label: 'Text' },
  file: { icon: '📄', label: 'File' },
};

const OUTCOME_COLORS: Record<string, string> = {
  memory: 'text-purple-400 bg-purple-400/10',
  collection: 'text-emerald-400 bg-emerald-400/10',
  thread: 'text-blue-400 bg-blue-400/10',
  'no output': 'text-neutral-500 bg-neutral-500/10',
};

export default function ConsumptionHistoryPanel() {
  const [data, setData] = useState<ConsumptionHistoryData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getConsumptionHistory();
      setData(result);
    } catch (err) {
      console.error('[ConsumptionHistory] Failed to fetch:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  const formatTimestamp = (ts: string | null): string => {
    if (!ts) return '—';
    try {
      const date = new Date(ts);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffM = Math.round(diffMs / (1000 * 60));
      if (diffM < 1) return 'just now';
      if (diffM < 60) return `${diffM}m ago`;
      const diffH = Math.round(diffM / 60);
      if (diffH < 24) return `${diffH}h ago`;
      return `${Math.round(diffH / 24)}d ago`;
    } catch {
      return ts;
    }
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Consumption History</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Consumption History</h2>
        <p className="text-sm text-neutral-500 font-mono">No data</p>
      </div>
    );
  }

  const entries = data.entries ?? [];

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Consumption History</h2>

      {entries.length === 0 ? (
        <p className="text-sm text-neutral-500 font-mono">No consumed content yet</p>
      ) : (
        <div className="max-h-96 overflow-y-auto space-y-2 pr-1">
          {entries.map((entry) => {
            const sourceInfo = SOURCE_TYPE_LABELS[entry.source_type] ?? {
              icon: '❓',
              label: entry.source_type,
            };

            return (
              <div
                key={entry.id}
                className="border-l-2 border-neutral-700 pl-3 py-1.5"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-xs flex-shrink-0" title={sourceInfo.label}>
                      {sourceInfo.icon}
                    </span>
                    <span className="text-sm font-mono text-neutral-200 truncate">
                      {entry.title}
                    </span>
                  </div>
                  <span className="text-xs font-mono text-neutral-500 flex-shrink-0">
                    {formatTimestamp(entry.consumed_at)}
                  </span>
                </div>
                <div className="flex gap-1.5 mt-1 flex-wrap">
                  {entry.outcomes.map((outcome) => (
                    <span
                      key={outcome}
                      className={`text-xs font-mono px-1.5 py-0.5 rounded ${OUTCOME_COLORS[outcome] ?? 'text-neutral-400 bg-neutral-700/50'}`}
                    >
                      → {outcome}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
