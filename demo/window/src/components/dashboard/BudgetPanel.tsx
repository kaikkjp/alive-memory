'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { BudgetData } from '@/lib/types';

export default function BudgetPanel() {
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [editing, setEditing] = useState(false);
  const [budgetInput, setBudgetInput] = useState('');
  const [saving, setSaving] = useState(false);

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

  const startEdit = () => {
    if (budget) {
      setBudgetInput(String(budget.budget));
      setEditing(true);
    }
  };

  const cancelEdit = () => {
    setEditing(false);
    setBudgetInput('');
  };

  const saveBudget = async () => {
    const val = parseFloat(budgetInput);
    if (isNaN(val) || val <= 0) return;
    setSaving(true);
    try {
      const result = await dashboardApi.setBudget(val);
      setBudget(result);
      setEditing(false);
      setBudgetInput('');
    } catch (err) {
      console.error('[BudgetPanel] Failed to set budget:', err);
    } finally {
      setSaving(false);
    }
  };

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

        {/* Budget cap editor */}
        <div className="pt-3 border-t border-neutral-700">
          {editing ? (
            <div className="flex gap-2">
              <input
                type="number"
                min={0.01}
                step="0.01"
                value={budgetInput}
                onChange={(e) => setBudgetInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveBudget();
                  if (e.key === 'Escape') cancelEdit();
                }}
                className="flex-1 px-3 py-1.5 bg-neutral-800 border border-neutral-600 rounded text-neutral-200 font-mono text-sm focus:outline-none focus:border-purple-500"
                autoFocus
                disabled={saving}
              />
              <button
                onClick={saveBudget}
                disabled={saving}
                className="px-3 py-1.5 bg-neutral-700 hover:bg-neutral-600 disabled:bg-neutral-800 disabled:text-neutral-600 text-neutral-200 font-mono text-xs rounded transition-colors"
              >
                {saving ? '...' : 'Save'}
              </button>
              <button
                onClick={cancelEdit}
                className="px-3 py-1.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-400 font-mono text-xs rounded transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={startEdit}
              className="text-xs font-mono text-neutral-500 hover:text-neutral-300 transition-colors"
            >
              Set daily cap
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
