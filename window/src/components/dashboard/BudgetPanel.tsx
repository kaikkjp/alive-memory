'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { BudgetData } from '@/lib/types';

export default function BudgetPanel() {
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchBudget = async () => {
    try {
      const data = await dashboardApi.getBudget();
      setBudget(data);
      setError(false);
    } catch (err) {
      console.error('[BudgetPanel] Failed to fetch:', err);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBudget();
    const interval = setInterval(fetchBudget, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Budget</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (error || !budget) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Budget</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  const pctUsed = budget.budget > 0 ? Math.min(1, budget.spent / budget.budget) : 0;
  const pctRemaining = 1 - pctUsed;
  const barColor =
    pctUsed >= 0.9 ? 'bg-red-500' :
    pctUsed >= 0.7 ? 'bg-amber-500' :
    'bg-emerald-500';

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Budget</h2>
      <div className="space-y-4">
        <div>
          <div className="text-xs text-neutral-500 font-mono">REMAINING</div>
          <div className={`text-2xl font-mono ${pctUsed >= 0.9 ? 'text-red-400' : pctUsed >= 0.7 ? 'text-amber-400' : 'text-emerald-400'}`}>
            ${budget.remaining.toFixed(4)}
          </div>
        </div>

        {/* Progress bar */}
        <div>
          <div className="flex justify-between text-xs font-mono text-neutral-500 mb-1">
            <span>SPENT ${budget.spent.toFixed(4)}</span>
            <span>CAP ${budget.budget.toFixed(2)}</span>
          </div>
          <div className="w-full h-2 bg-neutral-800 rounded overflow-hidden">
            <div
              className={`h-full ${barColor} transition-all duration-500`}
              style={{ width: `${pctUsed * 100}%` }}
            />
          </div>
          <div className="text-xs font-mono text-neutral-500 mt-1 text-right">
            {(pctRemaining * 100).toFixed(0)}% remaining
          </div>
        </div>
      </div>
    </div>
  );
}
