'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { FeedPanelData } from '@/lib/types';

const STATUS_COLORS: Record<string, string> = {
  running: 'text-green-400',
  paused: 'text-yellow-400',
  error: 'text-red-400',
};

const STATUS_DOT_COLORS: Record<string, string> = {
  running: 'bg-green-400',
  paused: 'bg-yellow-400',
  error: 'bg-red-400',
};

export default function FeedPanel() {
  const [data, setData] = useState<FeedPanelData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getFeed();
      setData(result);
    } catch (err) {
      console.error('Failed to fetch feed data:', err);
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
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Feed</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Feed</h2>
        <p className="text-sm text-neutral-500 font-mono">No data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Feed</h2>

      {/* Pipeline status */}
      <div className="flex items-center gap-2 mb-4">
        <span
          className={`inline-block w-2 h-2 rounded-full ${STATUS_DOT_COLORS[data.status] ?? 'bg-neutral-500'}`}
        />
        <span
          className={`text-sm font-mono capitalize ${STATUS_COLORS[data.status] ?? 'text-neutral-500'}`}
        >
          {data.status}
        </span>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <div className="text-xs text-neutral-500 font-mono">Queue</div>
          <div className="text-lg font-mono text-cyan-400">{data.queue_depth}</div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">24h rate</div>
          <div className="text-lg font-mono text-cyan-400">{data.rate_24h}</div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">Last ingestion</div>
          <div className="text-sm font-mono text-neutral-300">
            {formatTimestamp(data.last_success_ts)}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">Failed (24h)</div>
          <div
            className={`text-lg font-mono ${data.failed_24h > 0 ? 'text-red-400' : 'text-neutral-500'}`}
          >
            {data.failed_24h}
          </div>
        </div>
      </div>

      {/* Last error */}
      {data.last_error && (
        <div className="border-l-2 border-red-500 pl-3 mt-2">
          <div className="text-xs text-neutral-500 font-mono mb-1">Last error</div>
          <div className="text-xs text-red-300 font-mono truncate">
            {data.last_error}
          </div>
        </div>
      )}
    </div>
  );
}
