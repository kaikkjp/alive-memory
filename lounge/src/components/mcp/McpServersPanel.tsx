"use client";

import { useState, useEffect, useCallback } from "react";
import type { McpServer } from "@/lib/types";
import McpServerCard from "./McpServerCard";
import McpConnectDialog from "./McpConnectDialog";
import McpEmptyState from "./McpEmptyState";

interface Props {
  agentId: string;
}

export default function McpServersPanel({ agentId }: Props) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showConnect, setShowConnect] = useState(false);

  const fetchServers = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/mcp`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error || `Failed (${res.status})`);
      }
      const data = await res.json();
      setServers(Array.isArray(data) ? data : data.servers ?? []);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load servers");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchServers();
  }, [fetchServers]);

  function handleConnected() {
    setShowConnect(false);
    fetchServers();
  }

  if (loading) {
    return (
      <div className="text-sm text-[#525252] py-8 text-center">
        Loading tools...
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-[#ef4444] mb-3">{error}</p>
        <button
          onClick={() => { setLoading(true); fetchServers(); }}
          className="text-xs text-[#d4a574] hover:text-[#c4955a] transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-medium text-[#a3a3a3]">Connected Tools</h2>
        {servers.length > 0 && (
          <button
            onClick={() => setShowConnect(true)}
            className="px-3 py-1.5 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-xs font-medium transition-colors"
          >
            + Connect
          </button>
        )}
      </div>

      {/* Server list or empty state */}
      {servers.length === 0 ? (
        <McpEmptyState onConnect={() => setShowConnect(true)} />
      ) : (
        <div className="space-y-3">
          {servers.map((server) => (
            <McpServerCard
              key={server.id}
              server={server}
              agentId={agentId}
              onRefresh={fetchServers}
            />
          ))}
        </div>
      )}

      {/* Connect dialog */}
      {showConnect && (
        <McpConnectDialog
          agentId={agentId}
          onClose={() => setShowConnect(false)}
          onConnected={handleConnected}
        />
      )}
    </div>
  );
}
