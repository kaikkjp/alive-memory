'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';

interface Vitals {
  days_alive: number;
  visitors_today: number;
  cycles_today: number;
  llm_calls_today: number;
  cost_today: number;
}

export default function VitalsPanel() {
  const [vitals, setVitals] = useState<Vitals | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchVitals = async () => {
    try {
      const data = await dashboardApi.getVitals();
      setVitals(data);
    } catch (err) {
      console.error('Failed to fetch vitals:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVitals();
    const interval = setInterval(fetchVitals, 5000); // Refresh every 5s
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Vitals</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!vitals) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Vitals</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Vitals</h2>
      <div className="space-y-3">
        <div>
          <div className="text-xs text-neutral-500 font-mono">DAYS ALIVE</div>
          <div className="text-2xl font-mono text-emerald-400">
            {vitals.days_alive}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">VISITORS TODAY</div>
          <div className="text-2xl font-mono text-blue-400">
            {vitals.visitors_today}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">CYCLES TODAY</div>
          <div className="text-2xl font-mono text-purple-400">
            {vitals.cycles_today}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">LLM CALLS</div>
          <div className="text-2xl font-mono text-amber-400">
            {vitals.llm_calls_today}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">COST TODAY</div>
          <div className="text-2xl font-mono text-rose-400">
            ${vitals.cost_today.toFixed(4)}
          </div>
        </div>
      </div>
    </div>
  );
}
