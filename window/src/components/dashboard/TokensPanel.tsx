'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';

interface Token {
  token: string;
  display_name: string;
  uses_remaining: number | null;
  expires_at: string | null;
  created_at: string;
  active: boolean;
}

export default function TokensPanel() {
  const [tokens, setTokens] = useState<Token[]>([]);
  const [loading, setLoading] = useState(true);

  // Form state
  const [name, setName] = useState('');
  const [uses, setUses] = useState('');
  const [expires, setExpires] = useState('');
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<string | null>(null);

  const fetchTokens = async () => {
    try {
      const data = await dashboardApi.getTokens();
      setTokens(data.tokens || []);
    } catch (err) {
      console.error('Failed to fetch tokens:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTokens();
    const interval = setInterval(fetchTokens, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || creating) return;
    setCreating(true);
    setCreated(null);
    try {
      const parsedUses = uses.trim() ? parseInt(uses.trim(), 10) : undefined;
      const parsedExpires = expires.trim() || undefined;
      const data = await dashboardApi.createToken(name.trim(), parsedUses, parsedExpires);
      setCreated(data.token);
      setName('');
      setUses('');
      setExpires('');
      await fetchTokens();
    } catch (err) {
      console.error('Failed to create token:', err);
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (token: string) => {
    try {
      await dashboardApi.revokeToken(token);
      await fetchTokens();
    } catch (err) {
      console.error('Failed to revoke token:', err);
    }
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Invite Tokens</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Invite Tokens</h2>

      {/* Create form */}
      <form onSubmit={handleCreate} className="space-y-3 mb-4">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Visitor name"
          className="w-full px-3 py-1.5 bg-black border border-neutral-700 rounded text-neutral-100 font-mono text-sm focus:outline-none focus:border-neutral-500"
        />
        <div className="flex gap-2">
          <input
            type="text"
            value={uses}
            onChange={(e) => setUses(e.target.value)}
            placeholder="Uses (&#8734;)"
            className="w-1/2 px-3 py-1.5 bg-black border border-neutral-700 rounded text-neutral-100 font-mono text-sm focus:outline-none focus:border-neutral-500"
          />
          <input
            type="text"
            value={expires}
            onChange={(e) => setExpires(e.target.value)}
            placeholder="Expires (7d)"
            className="w-1/2 px-3 py-1.5 bg-black border border-neutral-700 rounded text-neutral-100 font-mono text-sm focus:outline-none focus:border-neutral-500"
          />
        </div>
        <button
          type="submit"
          disabled={creating || !name.trim()}
          className="w-full px-4 py-2 bg-purple-700 hover:bg-purple-600 disabled:bg-neutral-800 text-neutral-100 font-mono text-sm rounded transition-colors"
        >
          {creating ? 'Generating...' : 'Generate Token'}
        </button>
      </form>

      {/* Newly created token */}
      {created && (
        <div className="mb-4 p-3 bg-emerald-900/30 border border-emerald-700/50 rounded">
          <p className="text-xs text-emerald-400 font-mono mb-1">New token created:</p>
          <p className="text-sm text-emerald-300 font-mono break-all select-all">{created}</p>
        </div>
      )}

      {/* Token list */}
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {tokens.length === 0 && (
          <p className="text-sm text-neutral-500 font-mono">No tokens</p>
        )}
        {tokens.map((t) => (
          <div
            key={t.token}
            className="flex items-center justify-between p-2 bg-black/50 border border-neutral-800 rounded"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <div className={`h-2 w-2 rounded-full flex-shrink-0 ${t.active ? 'bg-emerald-500' : 'bg-neutral-600'}`} />
                <span className="text-sm text-neutral-200 font-mono truncate">
                  {t.display_name}
                </span>
              </div>
              <div className="text-xs text-neutral-500 font-mono mt-0.5 ml-4">
                {t.uses_remaining === null ? '\u221E' : t.uses_remaining} uses
                {t.expires_at && ` \u00B7 exp ${new Date(t.expires_at).toLocaleDateString()}`}
              </div>
            </div>
            <button
              onClick={() => handleRevoke(t.token)}
              className="text-xs text-neutral-600 hover:text-red-400 font-mono ml-2 flex-shrink-0 transition-colors"
              title="Revoke"
            >
              {'\u00D7'}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
