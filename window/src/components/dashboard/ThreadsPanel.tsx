'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { ThreadInfo } from '@/lib/types';

const STATUS_COLORS: Record<string, string> = {
  active: 'border-green-500',
  open: 'border-blue-500',
  dormant: 'border-neutral-600',
  closed: 'border-neutral-700',
};

const TYPE_LABELS: Record<string, string> = {
  question: 'Question',
  project: 'Project',
  anticipation: 'Anticipation',
  unresolved: 'Unresolved',
  ritual: 'Ritual',
};

function timeAgo(isoString: string | null | undefined): string {
  if (!isoString) return '';
  const diff = Date.now() - new Date(isoString).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function ThreadsPanel() {
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchThreads = async () => {
    try {
      const data = await dashboardApi.getThreads();
      const raw = data.threads || [];
      setThreads(
        raw.map((t: ThreadInfo) => ({
          id: t.id,
          title: t.title || '(untitled)',
          status: t.status || 'open',
          thread_type: t.thread_type,
          tags: t.tags || [],
          touch_count: t.touch_count ?? 0,
          last_touched: t.last_touched,
        }))
      );
    } catch (err) {
      console.error('Failed to fetch threads:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchThreads();
    const interval = setInterval(fetchThreads, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Threads</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Threads</h2>
      <div className="space-y-3 max-h-96 overflow-y-auto">
        {threads.length === 0 && (
          <p className="text-sm text-neutral-500 font-mono">No active threads</p>
        )}
        {threads.map((thread) => (
          <div
            key={thread.id}
            className={`border-l-2 ${STATUS_COLORS[thread.status] || 'border-neutral-600'} pl-3`}
          >
            <div className="text-sm text-neutral-300 font-mono truncate">
              {thread.title}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              {thread.thread_type && (
                <span className="text-xs text-neutral-500 font-mono">
                  {TYPE_LABELS[thread.thread_type] || thread.thread_type}
                </span>
              )}
              {thread.tags && thread.tags.length > 0 && (
                <>
                  <span className="text-neutral-700">·</span>
                  {thread.tags.slice(0, 3).map((tag) => (
                    <span
                      key={tag}
                      className="text-xs text-neutral-600 font-mono"
                    >
                      {tag}
                    </span>
                  ))}
                </>
              )}
            </div>
            <div className="flex items-center gap-3 mt-0.5 text-xs text-neutral-600 font-mono">
              <span>{thread.status}</span>
              {(thread.touch_count ?? 0) > 0 && (
                <>
                  <span className="text-neutral-700">·</span>
                  <span>{thread.touch_count} touches</span>
                </>
              )}
              {thread.last_touched && (
                <>
                  <span className="text-neutral-700">·</span>
                  <span>{timeAgo(thread.last_touched)}</span>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
