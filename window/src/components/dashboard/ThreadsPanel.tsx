'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';

interface ThreadInfo {
  id: string;
  title: string;
  status: string;
}

const STATUS_COLORS: Record<string, string> = {
  active: 'border-green-500',
  open: 'border-blue-500',
  dormant: 'border-neutral-600',
  closed: 'border-neutral-700',
};

export default function ThreadsPanel() {
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchThreads = async () => {
    try {
      const data = await dashboardApi.getThreads();
      // Support both old format (cycle logs) and new format (thread objects)
      const raw = data.threads || [];
      setThreads(
        raw.map((t: Record<string, string>) => ({
          id: t.id,
          title: t.title || t.dialogue || '(untitled)',
          status: t.status || 'open',
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
            <div className="text-sm text-neutral-300 font-mono">
              {thread.title}
            </div>
            <div className="text-xs text-neutral-500 font-mono">
              {thread.status}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
