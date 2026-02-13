'use client';

import { useState, useEffect } from 'react';

interface Thread {
  id: string;
  mode: string;
  dialogue: string;
  internal_monologue: string;
  ts: string;
}

export default function ThreadsPanel() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchThreads = async () => {
    try {
      const res = await fetch('http://localhost:8080/api/dashboard/threads');
      const data = await res.json();
      setThreads(data.threads || []);
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
          <p className="text-sm text-neutral-500 font-mono">No recent dialogue</p>
        )}
        {threads.map((thread) => (
          <div key={thread.id} className="border-l-2 border-blue-500 pl-3">
            <div className="text-xs text-neutral-500 font-mono mb-1">
              {new Date(thread.ts).toLocaleTimeString()} • {thread.mode}
            </div>
            <div className="text-sm text-neutral-300 font-mono mb-1">
              {thread.dialogue}
            </div>
            {thread.internal_monologue && (
              <div className="text-xs text-neutral-500 font-mono italic">
                {thread.internal_monologue.slice(0, 80)}
                {thread.internal_monologue.length > 80 ? '...' : ''}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
