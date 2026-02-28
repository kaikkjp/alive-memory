"use client";

import { useState } from "react";
import type { McpServer } from "@/lib/types";

interface Props {
  server: McpServer;
  agentId: string;
  onRefresh: () => void;
}

export default function McpServerCard({ server, agentId, onRefresh }: Props) {
  const [toggling, setToggling] = useState(false);
  const [togglingTool, setTogglingTool] = useState<string | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [error, setError] = useState("");

  async function handleToggleServer() {
    setToggling(true);
    setError("");
    try {
      const res = await fetch(`/api/agents/${agentId}/mcp/${server.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !server.enabled }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error || `Failed (${res.status})`);
      }
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setToggling(false);
    }
  }

  async function handleToggleTool(toolSuffix: string, currentEnabled: boolean) {
    setTogglingTool(toolSuffix);
    setError("");
    try {
      const res = await fetch(`/api/agents/${agentId}/mcp/${server.id}/tools/${toolSuffix}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !currentEnabled }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error || `Failed (${res.status})`);
      }
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setTogglingTool(null);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    setError("");
    try {
      const res = await fetch(`/api/agents/${agentId}/mcp/${server.id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error || `Failed (${res.status})`);
      }
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
      setDeleting(false);
      setShowDeleteConfirm(false);
      return;
    }
    setDeleting(false);
    setShowDeleteConfirm(false);
  }

  const connectedDate = new Date(server.connected_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  const totalUsage = server.tools.reduce((sum, t) => sum + t.usage_count, 0);

  return (
    <>
      <div
        className={`border rounded-lg transition-colors ${
          server.enabled
            ? "border-[#262620] bg-[#12121a]"
            : "border-[#1e1e1a] bg-[#0e0e14] opacity-60"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-2 min-w-0 flex-1 text-left"
          >
            <span className="text-[#525252] text-xs">{expanded ? "\u25BC" : "\u25B6"}</span>
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{server.name}</div>
              <div className="text-xs text-[#525252] truncate">{server.url}</div>
            </div>
          </button>

          <div className="flex items-center gap-3 shrink-0 ml-3">
            <span className="text-xs text-[#525252]">
              {server.tools.length} tool{server.tools.length !== 1 ? "s" : ""}
              {totalUsage > 0 && ` \u00B7 ${totalUsage} uses`}
            </span>

            {/* Server toggle */}
            <button
              onClick={handleToggleServer}
              disabled={toggling}
              className={`w-10 h-5 rounded-full transition-colors relative shrink-0 ${
                server.enabled ? "bg-[#d4a574]" : "bg-[#262626]"
              }`}
            >
              <div
                className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                  server.enabled ? "left-5" : "left-0.5"
                }`}
              />
            </button>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="border-t border-[#1e1e1a] px-4 py-2">
            <p className="text-xs text-[#ef4444]">{error}</p>
          </div>
        )}

        {/* Tools list */}
        {expanded && server.tools.length > 0 && (
          <div className="border-t border-[#1e1e1a] px-4 py-2 space-y-1">
            {server.tools.map((tool) => (
              <div
                key={tool.action_suffix}
                className="flex items-center justify-between py-1.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-mono text-[#a3a3a3] truncate">
                    {tool.name}
                  </div>
                  {tool.description && (
                    <div className="text-xs text-[#525252] truncate">{tool.description}</div>
                  )}
                </div>

                <div className="flex items-center gap-3 shrink-0 ml-3">
                  {tool.usage_count > 0 && (
                    <span className="text-xs text-[#525252]">{tool.usage_count}</span>
                  )}
                  <button
                    onClick={() => handleToggleTool(tool.action_suffix, tool.enabled)}
                    disabled={togglingTool === tool.action_suffix || !server.enabled}
                    className={`w-8 h-4 rounded-full transition-colors relative shrink-0 ${
                      tool.enabled ? "bg-[#d4a574]" : "bg-[#262626]"
                    } disabled:opacity-40`}
                  >
                    <div
                      className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
                        tool.enabled ? "left-4" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Footer */}
        {expanded && (
          <div className="border-t border-[#1e1e1a] px-4 py-2 flex items-center justify-between">
            <span className="text-xs text-[#525252]">Connected {connectedDate}</span>
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="text-[#ef4444] hover:text-[#dc2626] text-xs font-medium transition-colors"
            >
              Delete
            </button>
          </div>
        )}
      </div>

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-[#262620] rounded-xl p-6 max-w-md mx-4">
            <h3 className="text-lg font-semibold mb-2">Delete Server?</h3>
            <p className="text-sm text-[#a3a3a3] mb-1">
              <span className="font-medium text-white">{server.name}</span> and
              all its tools will be removed.
            </p>
            <p className="text-xs text-[#525252] mb-5">
              Usage history will be lost. The agent will lose access to these
              tools on the next cycle.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                disabled={deleting}
                className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="px-4 py-2 bg-[#ef4444] hover:bg-[#dc2626] text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
