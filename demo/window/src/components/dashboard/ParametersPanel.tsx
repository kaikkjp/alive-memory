'use client';

import { useState, useEffect, useCallback } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type {
  ParameterView,
  ParameterModification,
  ParametersPanelData,
} from '@/lib/types';

export default function ParametersPanel() {
  const [data, setData] = useState<ParametersPanelData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set()
  );
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const fetchParams = useCallback(async () => {
    try {
      const result = await dashboardApi.getParameters();
      setData(result);
    } catch (err) {
      console.error('Failed to fetch parameters:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchParams();
    const interval = setInterval(fetchParams, 15000); // Refresh every 15s
    return () => clearInterval(interval);
  }, [fetchParams]);

  const toggleCategory = (cat: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) {
        next.delete(cat);
      } else {
        next.add(cat);
      }
      return next;
    });
  };

  const startEdit = (param: ParameterView) => {
    setEditingKey(param.key);
    setEditValue(String(param.value));
    setError('');
  };

  const cancelEdit = () => {
    setEditingKey(null);
    setEditValue('');
    setError('');
  };

  const saveEdit = async (param: ParameterView) => {
    const numVal = parseFloat(editValue);
    if (isNaN(numVal)) {
      setError('Invalid number');
      return;
    }
    if (param.min_bound !== null && numVal < param.min_bound) {
      setError(`Min: ${param.min_bound}`);
      return;
    }
    if (param.max_bound !== null && numVal > param.max_bound) {
      setError(`Max: ${param.max_bound}`);
      return;
    }

    setSaving(true);
    try {
      await dashboardApi.setParameter(param.key, numVal);
      setEditingKey(null);
      setEditValue('');
      setError('');
      await fetchParams();
    } catch (err) {
      setError('Save failed');
    } finally {
      setSaving(false);
    }
  };

  const resetParam = async (param: ParameterView) => {
    setSaving(true);
    try {
      await dashboardApi.resetParameter(param.key);
      await fetchParams();
    } catch (err) {
      console.error('Reset failed:', err);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6 col-span-full">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Parameters</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6 col-span-full">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Parameters</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  const categoryOrder = [
    'hypothalamus',
    'thalamus',
    'sensorium',
    'basal_ganglia',
    'output',
    'sleep',
  ];
  const knownCategories = categoryOrder.filter(
    (c) => c in data.categories
  );
  // Append any categories from the API not in the known ordering
  const extraCategories = Object.keys(data.categories)
    .filter((c) => !categoryOrder.includes(c))
    .sort();
  const sortedCategories = [...knownCategories, ...extraCategories];

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6 col-span-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-mono text-neutral-300">
          Parameters{' '}
          <span className="text-xs text-neutral-500">
            ({data.total_count})
          </span>
        </h2>
      </div>

      {/* Category sections */}
      <div className="space-y-2">
        {sortedCategories.map((cat) => {
          const params = data.categories[cat];
          const isExpanded = expandedCategories.has(cat);
          const modifiedCount = params.filter(
            (p) => p.value !== p.default_value
          ).length;

          return (
            <div key={cat} className="border border-neutral-800 rounded">
              <button
                onClick={() => toggleCategory(cat)}
                className="w-full flex items-center justify-between px-4 py-2 text-left hover:bg-neutral-800 transition-colors"
              >
                <span className="font-mono text-sm text-neutral-200">
                  {cat}
                  <span className="text-neutral-500 ml-2">
                    ({params.length})
                  </span>
                  {modifiedCount > 0 && (
                    <span className="text-amber-400 ml-2">
                      {modifiedCount} modified
                    </span>
                  )}
                </span>
                <span className="text-neutral-500">
                  {isExpanded ? '▼' : '▶'}
                </span>
              </button>

              {isExpanded && (
                <div className="border-t border-neutral-800">
                  <table className="w-full text-xs font-mono">
                    <thead>
                      <tr className="text-neutral-500">
                        <th className="text-left px-4 py-1">Key</th>
                        <th className="text-right px-2 py-1 w-20">Value</th>
                        <th className="text-right px-2 py-1 w-20">Default</th>
                        <th className="text-right px-2 py-1 w-16">Bounds</th>
                        <th className="text-right px-2 py-1 w-16">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {params.map((param) => {
                        const isModified =
                          param.value !== param.default_value;
                        const isEditing = editingKey === param.key;

                        return (
                          <tr
                            key={param.key}
                            className={`border-t border-neutral-800/50 ${
                              isModified
                                ? 'bg-amber-900/10'
                                : 'hover:bg-neutral-800/50'
                            }`}
                            title={param.description}
                          >
                            <td className="px-4 py-1.5 text-neutral-300">
                              {param.key.replace(`${cat}.`, '')}
                              {param.description && (
                                <span className="text-neutral-600 ml-1 hidden lg:inline">
                                  — {param.description}
                                </span>
                              )}
                            </td>
                            <td className="text-right px-2 py-1.5">
                              {isEditing ? (
                                <input
                                  type="number"
                                  step="any"
                                  value={editValue}
                                  onChange={(e) =>
                                    setEditValue(e.target.value)
                                  }
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter')
                                      saveEdit(param);
                                    if (e.key === 'Escape')
                                      cancelEdit();
                                  }}
                                  className="w-20 px-1 py-0.5 bg-black border border-neutral-600 rounded text-right text-neutral-100 focus:outline-none focus:border-neutral-400"
                                  autoFocus
                                  disabled={saving}
                                />
                              ) : (
                                <span
                                  className={
                                    isModified
                                      ? 'text-amber-300'
                                      : 'text-neutral-200'
                                  }
                                >
                                  {param.value}
                                </span>
                              )}
                            </td>
                            <td className="text-right px-2 py-1.5 text-neutral-500">
                              {param.default_value}
                            </td>
                            <td className="text-right px-2 py-1.5 text-neutral-600">
                              {param.min_bound !== null &&
                              param.max_bound !== null
                                ? `${param.min_bound}..${param.max_bound}`
                                : '—'}
                            </td>
                            <td className="text-right px-2 py-1.5">
                              {isEditing ? (
                                <span className="space-x-1">
                                  <button
                                    onClick={() => saveEdit(param)}
                                    disabled={saving}
                                    className="text-green-400 hover:text-green-300"
                                  >
                                    ✓
                                  </button>
                                  <button
                                    onClick={cancelEdit}
                                    className="text-neutral-400 hover:text-neutral-300"
                                  >
                                    ✕
                                  </button>
                                </span>
                              ) : (
                                <span className="space-x-1">
                                  <button
                                    onClick={() => startEdit(param)}
                                    className="text-neutral-500 hover:text-neutral-300"
                                  >
                                    ✎
                                  </button>
                                  {isModified && (
                                    <button
                                      onClick={() => resetParam(param)}
                                      disabled={saving}
                                      className="text-neutral-500 hover:text-amber-300"
                                      title="Reset to default"
                                    >
                                      ↺
                                    </button>
                                  )}
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {error && editingKey && (
                    <p className="text-xs text-red-400 px-4 py-1">{error}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Recent modifications */}
      {data.recent_modifications.length > 0 && (
        <div className="mt-4 pt-4 border-t border-neutral-700">
          <h3 className="text-xs font-mono text-neutral-500 mb-2">
            Recent Changes
          </h3>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {data.recent_modifications.slice(0, 5).map((mod) => (
              <div
                key={mod.id}
                className="text-xs font-mono text-neutral-400 flex justify-between"
              >
                <span>
                  {mod.param_key}: {mod.old_value} → {mod.new_value}
                </span>
                <span className="text-neutral-600">
                  {mod.modified_by}
                  {mod.reason ? ` · ${mod.reason}` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
