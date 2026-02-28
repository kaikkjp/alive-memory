'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';

interface CostsSummary {
  today: number;
  '7d_avg': number;
  '30d_total': number;
  breakdown: Array<{
    purpose: string;
    cost: number;
    calls: number;
  }>;
}

interface CostsData {
  summary: CostsSummary;
  daily: Array<{
    date: string;
    cost: number;
  }>;
}

export default function CostsPanel() {
  const [costs, setCosts] = useState<CostsData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchCosts = async () => {
    try {
      const data = await dashboardApi.getCosts();
      setCosts(data);
    } catch (err) {
      console.error('Failed to fetch costs:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCosts();
    const interval = setInterval(fetchCosts, 10000); // Refresh every 10s
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Costs</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!costs) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Costs</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  const { summary } = costs;
  // TODO [TASK-031]: costs.daily contains 30-day daily breakdown — add trend chart

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Costs</h2>
      <div className="space-y-4">
        <div>
          <div className="text-xs text-neutral-500 font-mono">TODAY</div>
          <div className="text-2xl font-mono text-emerald-400">
            ${summary.today.toFixed(4)}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">7-DAY AVG</div>
          <div className="text-xl font-mono text-blue-400">
            ${summary['7d_avg'].toFixed(4)}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500 font-mono">30-DAY TOTAL</div>
          <div className="text-xl font-mono text-purple-400">
            ${summary['30d_total'].toFixed(4)}
          </div>
        </div>
        {summary.breakdown.length > 0 && (
          <div className="pt-3 border-t border-neutral-700">
            <div className="text-xs text-neutral-500 font-mono mb-2">BREAKDOWN</div>
            <div className="space-y-1">
              {summary.breakdown.map((item) => (
                <div
                  key={item.purpose}
                  className="flex justify-between text-xs font-mono text-neutral-400"
                >
                  <span>{item.purpose}</span>
                  <span>${item.cost.toFixed(4)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
