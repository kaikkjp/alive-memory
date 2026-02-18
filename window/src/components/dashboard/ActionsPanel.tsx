'use client';

import { useState, useEffect, useCallback } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { DynamicAction, ActionsPanelData } from '@/lib/types';

const STATUS_ORDER = ['pending', 'promoted', 'alias', 'body_state', 'rejected'] as const;

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  promoted: 'Promoted',
  alias: 'Alias',
  body_state: 'Body State',
  rejected: 'Rejected',
};

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-amber-300',
  promoted: 'text-green-400',
  alias: 'text-blue-400',
  body_state: 'text-purple-400',
  rejected: 'text-neutral-600',
};

export default function ActionsPanel() {
  const [data, setData] = useState<ActionsPanelData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedStatuses, setExpandedStatuses] = useState<Set<string>>(
    new Set(['pending', 'promoted'])
  );
  const [resolving, setResolving] = useState<string | null>(null);

  const fetchActions = useCallback(async () => {
    try {
      const result = await dashboardApi.getActions();
      setData(result);
    } catch (err) {
      console.error('Failed to fetch actions:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchActions();
    const interval = setInterval(fetchActions, 15000);
    return () => clearInterval(interval);
  }, [fetchActions]);

  const toggleStatus = (status: string) => {
    setExpandedStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(status)) {
        next.delete(status);
      } else {
        next.add(status);
      }
      return next;
    });
  };

  const handleAlias = async (action: DynamicAction) => {
    const target = window.prompt(
      `Map "${action.action_name}" as alias for which existing action?`,
      action.alias_for ?? ''
    );
    if (!target || !target.trim()) return;
    setResolving(action.action_name);
    try {
      await dashboardApi.resolveAction(action.action_name, 'alias', target.trim());
      await fetchActions();
    } catch (err) {
      console.error('Failed to resolve action:', err);
    } finally {
      setResolving(null);
    }
  };

  const handleReject = async (action: DynamicAction) => {
    setResolving(action.action_name);
    try {
      await dashboardApi.resolveAction(action.action_name, 'rejected');
      await fetchActions();
    } catch (err) {
      console.error('Failed to reject action:', err);
    } finally {
      setResolving(null);
    }
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6 col-span-full">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Dynamic Actions</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6 col-span-full">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Dynamic Actions</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  const actionsByStatus = STATUS_ORDER.reduce<Record<string, DynamicAction[]>>(
    (acc, status) => {
      acc[status] = data.actions.filter((a) => a.status === status);
      return acc;
    },
    {}
  );

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6 col-span-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-mono text-neutral-300">
          Dynamic Actions{' '}
          <span className="text-xs text-neutral-500">({data.stats.total})</span>
        </h2>
      </div>

      {/* Stats bar */}
      <div className="flex flex-wrap gap-3 mb-4 text-xs font-mono">
        {Object.entries(data.stats.by_status).map(([status, count]) => (
          <span key={status} className={STATUS_COLORS[status] ?? 'text-neutral-400'}>
            {STATUS_LABELS[status] ?? status}: {count}
          </span>
        ))}
      </div>

      {/* Top pending */}
      {data.stats.top_pending.length > 0 && (
        <div className="mb-4 p-3 bg-amber-900/10 border border-amber-800/30 rounded text-xs font-mono">
          <span className="text-amber-500 mr-2">Top pending:</span>
          {data.stats.top_pending.map((item, i) => (
            <span key={item.action_name} className="text-neutral-300">
              {i > 0 && <span className="text-neutral-600 mx-1">·</span>}
              {item.action_name}
              <span className="text-neutral-500 ml-1">({item.attempt_count}x)</span>
            </span>
          ))}
        </div>
      )}

      {/* Status sections */}
      <div className="space-y-2">
        {STATUS_ORDER.filter((status) => actionsByStatus[status].length > 0).map((status) => {
          const actions = actionsByStatus[status];
          const isExpanded = expandedStatuses.has(status);

          return (
            <div key={status} className="border border-neutral-800 rounded">
              <button
                onClick={() => toggleStatus(status)}
                className="w-full flex items-center justify-between px-4 py-2 text-left hover:bg-neutral-800 transition-colors"
              >
                <span className="font-mono text-sm">
                  <span className={STATUS_COLORS[status] ?? 'text-neutral-300'}>
                    {STATUS_LABELS[status] ?? status}
                  </span>
                  <span className="text-neutral-500 ml-2">({actions.length})</span>
                </span>
                <span className="text-neutral-500">{isExpanded ? '▼' : '▶'}</span>
              </button>

              {isExpanded && (
                <div className="border-t border-neutral-800">
                  <table className="w-full text-xs font-mono">
                    <thead>
                      <tr className="text-neutral-500">
                        <th className="text-left px-4 py-1">Action</th>
                        <th className="text-right px-2 py-1 w-16">Count</th>
                        <th className="text-left px-2 py-1">Detail</th>
                        <th className="text-left px-2 py-1 hidden md:table-cell">Last seen</th>
                        {status === 'pending' && (
                          <th className="text-right px-2 py-1 w-24">Resolve</th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {actions.map((action) => {
                        const nearThreshold =
                          status === 'pending' &&
                          action.attempt_count >= action.promote_threshold;

                        return (
                          <tr
                            key={action.action_name}
                            className={`border-t border-neutral-800/50 ${
                              nearThreshold
                                ? 'bg-amber-900/15'
                                : 'hover:bg-neutral-800/50'
                            }`}
                          >
                            <td className="px-4 py-1.5 text-neutral-200">
                              {action.action_name}
                              {nearThreshold && (
                                <span className="text-amber-400 ml-2 text-xs">
                                  near threshold
                                </span>
                              )}
                            </td>
                            <td className="text-right px-2 py-1.5 text-neutral-400">
                              {action.attempt_count}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-500">
                              {action.alias_for && (
                                <span>
                                  alias:{' '}
                                  <span className="text-blue-400">{action.alias_for}</span>
                                </span>
                              )}
                              {action.body_state && (
                                <span>
                                  state:{' '}
                                  <span className="text-purple-400 break-all">
                                    {action.body_state}
                                  </span>
                                </span>
                              )}
                              {action.resolved_by && (
                                <span className="text-neutral-600">
                                  by {action.resolved_by}
                                </span>
                              )}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-600 hidden md:table-cell">
                              {action.last_seen
                                ? new Date(action.last_seen).toLocaleDateString()
                                : '—'}
                            </td>
                            {status === 'pending' && (
                              <td className="text-right px-2 py-1.5">
                                <span className="space-x-2">
                                  <button
                                    onClick={() => handleAlias(action)}
                                    disabled={resolving === action.action_name}
                                    className="text-blue-500 hover:text-blue-300 disabled:opacity-40"
                                    title="Mark as alias"
                                  >
                                    alias
                                  </button>
                                  <button
                                    onClick={() => handleReject(action)}
                                    disabled={resolving === action.action_name}
                                    className="text-neutral-500 hover:text-red-400 disabled:opacity-40"
                                    title="Reject"
                                  >
                                    reject
                                  </button>
                                </span>
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
