'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { ContentPoolData } from '@/lib/types';

export default function ContentPoolPanel() {
  const [data, setData] = useState<ContentPoolData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getContentPool();
      setData(result);
    } catch (err) {
      console.error('Failed to fetch content pool:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  const formatAge = (hours: number | null): string => {
    if (hours === null) return '—';
    if (hours < 1) return `${Math.round(hours * 60)}m`;
    if (hours < 24) return `${Math.round(hours)}h`;
    return `${Math.round(hours / 24)}d`;
  };

  const formatTimestamp = (ts: string): string => {
    try {
      const date = new Date(ts);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffH = diffMs / (1000 * 60 * 60);
      if (diffH < 1) return `${Math.round(diffH * 60)}m ago`;
      if (diffH < 24) return `${Math.round(diffH)}h ago`;
      return `${Math.round(diffH / 24)}d ago`;
    } catch {
      return ts;
    }
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Content Pool</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Content Pool</h2>
        <p className="text-sm text-neutral-500 font-mono">No data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Content Pool</h2>

      {/* Summary stats */}
      <div className="flex items-center gap-4 mb-4">
        <div className="text-2xl font-mono text-cyan-400">{data.total}</div>
        <div className="text-xs text-neutral-500 font-mono">unseen items</div>
        {data.oldest_age_hours !== null && (
          <div className="ml-auto text-xs text-neutral-500 font-mono">
            oldest: <span className="text-amber-400">{formatAge(data.oldest_age_hours)}</span>
          </div>
        )}
      </div>

      {/* Type breakdown */}
      {data.by_type.length > 0 && (
        <div className="mb-4">
          <div className="flex flex-wrap gap-2">
            {data.by_type.map((t) => (
              <span
                key={t.source_type}
                className="text-xs font-mono px-2 py-1 rounded bg-neutral-800 text-neutral-300"
              >
                {t.source_type} <span className="text-cyan-400">{t.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Recent items */}
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {data.recent.length === 0 && (
          <p className="text-sm text-neutral-500 font-mono">Pool empty</p>
        )}
        {data.recent.map((item, i) => (
          <div key={i} className="border-l-2 border-cyan-500 pl-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-neutral-300 font-mono truncate flex-1">
                {item.title}
              </span>
              <span className="text-xs text-neutral-500 font-mono shrink-0">
                {item.source_type}
              </span>
            </div>
            <div className="text-xs text-neutral-600 font-mono">
              {formatTimestamp(item.added_at)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
