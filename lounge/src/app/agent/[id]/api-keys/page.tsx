"use client";

import { useState, useEffect, use } from "react";
import AgentNav from "@/components/AgentNav";

interface MaskedApiKey {
  id: string;
  agent_id: string;
  key: string; // masked
  name: string;
  rate_limit: number;
  created_at: string;
}

export default function ApiKeysPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [keys, setKeys] = useState<MaskedApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyRate, setNewKeyRate] = useState("60");
  const [creating, setCreating] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    fetchKeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function fetchKeys() {
    try {
      const res = await fetch(`/api/agents/${id}/api-keys`);
      if (res.ok) {
        const data = await res.json();
        setKeys(data.api_keys || []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const name = newKeyName.trim();
    if (!name) return;

    setCreating(true);
    setError("");

    try {
      const res = await fetch(`/api/agents/${id}/api-keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          rate_limit: parseInt(newKeyRate) || 60,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setCreatedKey(data.api_key.key);
        setNewKeyName("");
        setNewKeyRate("60");
        fetchKeys();
      } else {
        const data = await res.json();
        setError(data.error || "Failed to create key");
      }
    } catch {
      setError("Connection error");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(keyId: string) {
    setDeleting(keyId);
    try {
      const res = await fetch(`/api/agents/${id}/api-keys/${keyId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setKeys((prev) => prev.filter((k) => k.id !== keyId));
      }
    } catch {
      // ignore
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="flex flex-col h-screen">
      <AgentNav agentId={id} active="api-keys" />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-lg font-semibold">API Keys</h2>
              <p className="text-sm text-[#737373]">
                Keys used by external apps to interact with this agent.
              </p>
            </div>
            <button
              onClick={() => {
                setShowCreate(true);
                setCreatedKey(null);
              }}
              className="px-4 py-2 bg-[#3b82f6] hover:bg-[#2563eb] rounded-lg text-sm font-medium transition-colors"
            >
              Create Key
            </button>
          </div>

          {/* Created key banner */}
          {createdKey && (
            <div className="mb-6 bg-[#14532d]/30 border border-[#22c55e]/30 rounded-lg p-4">
              <p className="text-sm text-[#22c55e] font-medium mb-2">
                New API key created. Copy it now — it won&apos;t be shown again.
              </p>
              <code className="block bg-[#0a0a0a] px-3 py-2 rounded text-sm font-mono break-all">
                {createdKey}
              </code>
            </div>
          )}

          {/* Create form */}
          {showCreate && !createdKey && (
            <form
              onSubmit={handleCreate}
              className="mb-6 bg-[#141414] border border-[#262626] rounded-lg p-4"
            >
              <h3 className="text-sm font-medium mb-3">New API Key</h3>
              <div className="flex flex-col sm:flex-row gap-3">
                <input
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="Key name (e.g., My App)"
                  className="flex-1 px-3 py-2 bg-[#0a0a0a] border border-[#262626] rounded-lg text-sm focus:outline-none focus:border-[#3b82f6]"
                />
                <div className="flex items-center gap-2">
                  <input
                    value={newKeyRate}
                    onChange={(e) => setNewKeyRate(e.target.value)}
                    type="number"
                    min="1"
                    max="1000"
                    className="w-20 px-3 py-2 bg-[#0a0a0a] border border-[#262626] rounded-lg text-sm focus:outline-none focus:border-[#3b82f6]"
                  />
                  <span className="text-xs text-[#737373] whitespace-nowrap">
                    req/min
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={creating || !newKeyName.trim()}
                    className="px-4 py-2 bg-[#3b82f6] hover:bg-[#2563eb] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                  >
                    {creating ? "Creating..." : "Create"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowCreate(false)}
                    className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
              {error && (
                <p className="mt-2 text-sm text-[#ef4444]">{error}</p>
              )}
            </form>
          )}

          {/* Keys table */}
          {loading ? (
            <p className="text-sm text-[#737373]">Loading keys...</p>
          ) : keys.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-[#737373] text-sm mb-1">No API keys yet.</p>
              <p className="text-[#525252] text-xs">
                Create a key to let external apps talk to this agent.
              </p>
            </div>
          ) : (
            <div className="border border-[#262626] rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-[#141414] text-[#737373] text-xs uppercase">
                    <th className="text-left px-4 py-3 font-medium">Name</th>
                    <th className="text-left px-4 py-3 font-medium">Key</th>
                    <th className="text-left px-4 py-3 font-medium hidden sm:table-cell">
                      Rate Limit
                    </th>
                    <th className="text-left px-4 py-3 font-medium hidden md:table-cell">
                      Created
                    </th>
                    <th className="text-right px-4 py-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#262626]">
                  {keys.map((k) => (
                    <tr key={k.id} className="hover:bg-[#141414] transition-colors">
                      <td className="px-4 py-3">{k.name}</td>
                      <td className="px-4 py-3 font-mono text-[#737373] text-xs">
                        {k.key}
                      </td>
                      <td className="px-4 py-3 text-[#737373] hidden sm:table-cell">
                        {k.rate_limit}/min
                      </td>
                      <td className="px-4 py-3 text-[#737373] hidden md:table-cell">
                        {new Date(k.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => handleRevoke(k.id)}
                          disabled={deleting === k.id}
                          className="text-[#ef4444] hover:text-[#dc2626] text-xs font-medium disabled:opacity-50 transition-colors"
                        >
                          {deleting === k.id ? "Revoking..." : "Revoke"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
