'use client';

import { dashboardApi } from '@/lib/dashboard-api';
import { useState, useEffect } from 'react';

interface PoolMoment {
  id: string;
  summary: string;
  salience: number;
  moment_type: string;
  visitor_id: string | null;
  ts: string;
}

export default function PoolPanel() {
  const [pool, setPool] = useState<PoolMoment[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPool = async () => {
    try {
      const data = await dashboardApi.getPool();
      setPool(data.pool || []);
    } catch (err) {
      console.error('Failed to fetch pool:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPool();
    const interval = setInterval(fetchPool, 15000);
    return () => clearInterval(interval);
  }, []);

  const getSalienceColor = (salience: number) => {
    if (salience >= 0.7) return 'text-rose-400';
    if (salience >= 0.5) return 'text-amber-400';
    return 'text-blue-400';
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Memory Pool</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Memory Pool</h2>
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {pool.length === 0 && (
          <p className="text-sm text-neutral-500 font-mono">No memories yet</p>
        )}
        {pool.map((moment) => (
          <div key={moment.id} className="border-l-2 border-purple-500 pl-3">
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-sm font-mono font-bold ${getSalienceColor(moment.salience)}`}>
                {Math.round(moment.salience * 100)}%
              </span>
              <span className="text-xs text-neutral-500 font-mono">
                {moment.moment_type}
              </span>
            </div>
            <div className="text-sm text-neutral-300 font-mono">
              {moment.summary}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
