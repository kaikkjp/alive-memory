"use client";

import { useState, useEffect, useCallback } from "react";
import type { DynamicAction, DynamicActionsData } from "@/lib/types";

const STATUS_ORDER = [
  "pending",
  "promoted",
  "alias",
  "body_state",
  "rejected",
] as const;

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  promoted: "Promoted",
  alias: "Alias",
  body_state: "Body State",
  rejected: "Rejected",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "text-amber-300",
  promoted: "text-green-400",
  alias: "text-blue-400",
  body_state: "text-purple-400",
  rejected: "text-[#525252]",
};

export default function DynamicActionsPanel({
  agentId,
}: {
  agentId: string;
}) {
  const [data, setData] = useState<DynamicActionsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(
    new Set(["pending", "promoted"])
  );
  const [resolving, setResolving] = useState<string | null>(null);

  const fetchActions = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/actions`);
      if (!res.ok) {
        if (res.status === 502) {
          setError("offline");
        } else {
          setError("failed");
        }
        return;
      }
      const result: DynamicActionsData = await res.json();
      // Filter noise: hide pending with < 2 attempts
      const filtered = result.actions.filter(
        (a) => a.status !== "pending" || a.attempt_count >= 2
      );
      const hiddenCount = result.actions.length - filtered.length;
      result.actions = filtered;
      // Reconcile stats with visible actions
      if (hiddenCount > 0) {
        result.stats.total -= hiddenCount;
        result.stats.by_status = { ...result.stats.by_status };
        result.stats.by_status.pending = Math.max(
          0,
          (result.stats.by_status.pending ?? 0) - hiddenCount
        );
        result.stats.top_pending = result.stats.top_pending.filter(
          (tp) => filtered.some((a) => a.action_name === tp.action_name)
        );
      }
      setData(result);
      setError(null);
    } catch {
      setError("failed");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchActions();
    const interval = setInterval(fetchActions, 30_000);
    return () => clearInterval(interval);
  }, [fetchActions]);

  const toggle = (status: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  };

  const handleAlias = async (action: DynamicAction) => {
    const target = window.prompt(
      `Map "${action.action_name}" as alias for which action?`,
      action.alias_for ?? ""
    );
    if (!target?.trim()) return;
    setResolving(action.action_name);
    try {
      await fetch(`/api/agents/${agentId}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action_name: action.action_name,
          status: "alias",
          alias_for: target.trim(),
        }),
      });
      await fetchActions();
    } catch (err) {
      console.error("Failed to alias action:", err);
    } finally {
      setResolving(null);
    }
  };

  const handleReject = async (action: DynamicAction) => {
    setResolving(action.action_name);
    try {
      await fetch(`/api/agents/${agentId}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action_name: action.action_name,
          status: "rejected",
        }),
      });
      await fetchActions();
    } catch (err) {
      console.error("Failed to reject action:", err);
    } finally {
      setResolving(null);
    }
  };

  if (loading) {
    return (
      <div className="border border-[#1e1e1a] rounded-lg p-6 mt-6">
        <h2 className="text-sm font-medium text-[#737373] uppercase tracking-wider mb-3">
          Dynamic Actions
        </h2>
        <p className="text-xs text-[#525252]">Loading...</p>
      </div>
    );
  }

  if (error === "offline") {
    return (
      <div className="border border-[#1e1e1a] rounded-lg p-6 mt-6">
        <h2 className="text-sm font-medium text-[#737373] uppercase tracking-wider mb-3">
          Dynamic Actions
        </h2>
        <p className="text-xs text-[#525252] italic">Agent offline</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="border border-[#1e1e1a] rounded-lg p-6 mt-6">
        <h2 className="text-sm font-medium text-[#737373] uppercase tracking-wider mb-3">
          Dynamic Actions
        </h2>
        <p className="text-xs text-red-400/60">Failed to load</p>
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

  const nonEmpty = STATUS_ORDER.filter(
    (s) => actionsByStatus[s].length > 0
  );

  return (
    <div className="border border-[#1e1e1a] rounded-lg p-6 mt-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-medium text-[#737373] uppercase tracking-wider">
          Dynamic Actions
          <span className="text-[#525252] ml-2 normal-case">
            ({data.stats.total})
          </span>
        </h2>
      </div>

      {/* Stats */}
      <div className="flex flex-wrap gap-3 mb-4 text-xs">
        {Object.entries(data.stats.by_status).map(([status, count]) => (
          <span
            key={status}
            className={STATUS_COLORS[status] ?? "text-[#525252]"}
          >
            {STATUS_LABELS[status] ?? status}: {count}
          </span>
        ))}
      </div>

      {/* Top pending callout */}
      {data.stats.top_pending.length > 0 && (
        <div className="mb-4 p-3 bg-amber-900/10 border border-amber-800/20 rounded text-xs">
          <span className="text-amber-500/80 mr-2">Needs attention:</span>
          {data.stats.top_pending.map((item, i) => (
            <span key={item.action_name} className="text-[#a3a3a3]">
              {i > 0 && (
                <span className="text-[#525252] mx-1">&middot;</span>
              )}
              {item.action_name}
              <span className="text-[#525252] ml-1">
                ({item.attempt_count}x)
              </span>
            </span>
          ))}
        </div>
      )}

      {nonEmpty.length === 0 && (
        <p className="text-xs text-[#525252] italic">
          No dynamic actions yet. Actions appear as the agent invents them.
        </p>
      )}

      {/* Status sections */}
      <div className="space-y-2">
        {nonEmpty.map((status) => {
          const actions = actionsByStatus[status];
          const isExpanded = expanded.has(status);

          return (
            <div key={status} className="border border-[#1e1e1a] rounded">
              <button
                onClick={() => toggle(status)}
                className="w-full flex items-center justify-between px-4 py-2 text-left hover:bg-[#1a1a1a] transition-colors"
              >
                <span className="text-xs">
                  <span className={STATUS_COLORS[status] ?? "text-[#a3a3a3]"}>
                    {STATUS_LABELS[status] ?? status}
                  </span>
                  <span className="text-[#525252] ml-2">
                    ({actions.length})
                  </span>
                </span>
                <span className="text-[#525252] text-xs">
                  {isExpanded ? "\u25BC" : "\u25B6"}
                </span>
              </button>

              {isExpanded && (
                <div className="border-t border-[#1e1e1a]">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-[#525252]">
                        <th className="text-left px-4 py-1.5 font-normal">
                          Action
                        </th>
                        <th className="text-right px-2 py-1.5 w-14 font-normal">
                          Count
                        </th>
                        <th className="text-left px-2 py-1.5 font-normal">
                          Detail
                        </th>
                        {status === "pending" && (
                          <th className="text-right px-2 py-1.5 w-24 font-normal">
                            Resolve
                          </th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {actions.map((action) => {
                        const nearThreshold =
                          status === "pending" &&
                          action.attempt_count >= action.promote_threshold;

                        return (
                          <tr
                            key={action.action_name}
                            className={`border-t border-[#1e1e1a]/50 ${
                              nearThreshold
                                ? "bg-amber-900/10"
                                : "hover:bg-[#1a1a1a]/50"
                            }`}
                          >
                            <td className="px-4 py-1.5 text-[#a3a3a3]">
                              {action.action_name}
                              {nearThreshold && (
                                <span className="text-amber-400/70 ml-2 text-[10px]">
                                  near threshold
                                </span>
                              )}
                            </td>
                            <td className="text-right px-2 py-1.5 text-[#525252]">
                              {action.attempt_count}
                            </td>
                            <td className="px-2 py-1.5 text-[#525252]">
                              {action.alias_for && (
                                <span>
                                  alias:{" "}
                                  <span className="text-blue-400/70">
                                    {action.alias_for}
                                  </span>
                                </span>
                              )}
                              {action.body_state && (
                                <span>
                                  state:{" "}
                                  <span className="text-purple-400/70 break-all">
                                    {action.body_state}
                                  </span>
                                </span>
                              )}
                              {action.resolved_by && (
                                <span className="text-[#525252]">
                                  by {action.resolved_by}
                                </span>
                              )}
                            </td>
                            {status === "pending" && (
                              <td className="text-right px-2 py-1.5">
                                <span className="space-x-2">
                                  <button
                                    onClick={() => handleAlias(action)}
                                    disabled={
                                      resolving === action.action_name
                                    }
                                    className="text-blue-400/70 hover:text-blue-300 disabled:opacity-40"
                                    title="Map as alias for existing action"
                                  >
                                    alias
                                  </button>
                                  <button
                                    onClick={() => handleReject(action)}
                                    disabled={
                                      resolving === action.action_name
                                    }
                                    className="text-[#525252] hover:text-red-400/70 disabled:opacity-40"
                                    title="Reject this action"
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
