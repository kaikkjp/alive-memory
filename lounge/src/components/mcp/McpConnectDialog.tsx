"use client";

import { useState } from "react";

interface Props {
  agentId: string;
  onClose: () => void;
  onConnected: () => void;
}

export default function McpConnectDialog({ agentId, onClose, onConnected }: Props) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleConnect() {
    if (!url.trim()) {
      setError("URL is required");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/agents/${agentId}/mcp/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), name: name.trim() || undefined }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error || `Failed (${res.status})`);
      }
      onConnected();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-[#262620] rounded-xl p-6 max-w-md w-full mx-4">
        <h3 className="text-lg font-semibold mb-4">Connect MCP Server</h3>

        <label className="block text-xs text-[#737373] mb-1">Name (optional)</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Product Search"
          className="w-full px-3 py-2 bg-[#12121a] border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] transition-colors mb-3"
        />

        <label className="block text-xs text-[#737373] mb-1">Server URL</label>
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://mcp.example.com"
          className="w-full px-3 py-2 bg-[#12121a] border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] transition-colors mb-1"
          onKeyDown={(e) => e.key === "Enter" && !loading && handleConnect()}
        />
        {error && <p className="text-xs text-[#ef4444] mt-1">{error}</p>}

        <div className="flex gap-3 justify-end mt-5">
          <button
            onClick={onClose}
            disabled={loading}
            className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConnect}
            disabled={loading}
            className="px-4 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {loading ? "Connecting..." : "Connect"}
          </button>
        </div>
      </div>
    </div>
  );
}
