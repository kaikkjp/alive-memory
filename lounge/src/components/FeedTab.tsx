"use client";

import { useState, useEffect, useCallback } from "react";
import type { FeedDrop, FeedStream } from "@/lib/types";

interface FeedTabProps {
  agentId: string;
  status: "connected" | "reconnecting" | "offline" | "error";
}

export default function FeedTab({ agentId, status }: FeedTabProps) {
  const isOffline = status === "offline" || status === "error";

  return (
    <div className="space-y-6">
      <DropSection agentId={agentId} isOffline={isOffline} />
      <StreamSection agentId={agentId} isOffline={isOffline} />
      {/* Knowledge placeholder */}
      <div className="p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg">
        <span className="text-xs text-[#525252]">
          Knowledge base — coming soon
        </span>
      </div>
    </div>
  );
}

/* ── Drop Section ── */

function DropSection({
  agentId,
  isOffline,
}: {
  agentId: string;
  isOffline: boolean;
}) {
  const [drops, setDrops] = useState<FeedDrop[]>([]);
  const [loading, setLoading] = useState(true);
  const [notAvailable, setNotAvailable] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const fetchDrops = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/feed/drops?limit=10`);
      if (res.status === 404) {
        setNotAvailable(true);
        return;
      }
      if (res.ok) {
        const data = await res.json();
        setDrops(Array.isArray(data) ? data : data.drops || []);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchDrops();
  }, [fetchDrops]);

  async function handleDrop() {
    if (!title.trim() || !content.trim() || sending) return;
    setSending(true);
    setError("");
    try {
      const isUrl = /^https?:\/\//i.test(content.trim());
      const body: Record<string, string> = { title: title.trim() };
      if (isUrl) body.url = content.trim();
      else body.text = content.trim();

      const res = await fetch(`/api/agents/${agentId}/feed/drops`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 404) {
        setNotAvailable(true);
        return;
      }
      if (res.ok) {
        setTitle("");
        setContent("");
        await fetchDrops();
      } else {
        setError("Failed to drop content");
      }
    } catch {
      setError("Connection error");
    } finally {
      setSending(false);
    }
  }

  if (notAvailable) {
    return (
      <div className="p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg">
        <h3 className="text-xs font-medium text-[#9a8c7a] mb-1">
          Content Drops
        </h3>
        <p className="text-xs text-[#525252]">
          Not available yet — coming in a future update
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium text-[#9a8c7a] uppercase tracking-wider">
        Drop Content
      </h3>

      {/* Drop form */}
      <div className="space-y-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title"
          className="w-full px-3 py-2 bg-[#12121a] border border-[#262620] rounded-lg text-xs focus:outline-none focus:border-[#d4a574] transition-colors disabled:opacity-40"
          disabled={isOffline}
        />
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Paste a URL or write text..."
          rows={3}
          className="w-full px-3 py-2 bg-[#12121a] border border-[#262620] rounded-lg text-xs focus:outline-none focus:border-[#d4a574] transition-colors resize-y disabled:opacity-40"
          disabled={isOffline}
        />
        {error && <p className="text-xs text-[#ef4444]">{error}</p>}
        <button
          onClick={handleDrop}
          disabled={
            sending || !title.trim() || !content.trim() || isOffline
          }
          className="w-full py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-xs font-medium disabled:opacity-50 transition-colors"
        >
          {sending ? "Dropping..." : "Drop into feed"}
        </button>
      </div>

      {/* Recent drops */}
      {!loading && drops.length > 0 && (
        <div className="space-y-2">
          <span className="text-xs text-[#525252]">Recent drops</span>
          {drops.map((drop) => (
            <div
              key={drop.id}
              className="p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-[#d4d4d4] truncate mr-2">
                  {drop.title}
                </span>
                <DropStatusBadge status={drop.status} />
              </div>
              {drop.status === "consumed" && drop.consumption_output && (
                <p className="text-xs text-[#9a8c7a] italic mt-1 line-clamp-2">
                  She wrote: &ldquo;{drop.consumption_output}&rdquo;
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      {loading && (
        <div className="text-xs text-[#525252]">Loading drops...</div>
      )}
    </div>
  );
}

function DropStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    consumed: "text-emerald-500 bg-emerald-500/10",
    pending: "text-amber-500 bg-amber-500/10",
    skipped: "text-[#525252] bg-[#1e1e1a]",
  };
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded-full ${styles[status] || styles.pending}`}
    >
      {status}
    </span>
  );
}

/* ── Stream Section ── */

function StreamSection({
  agentId,
  isOffline,
}: {
  agentId: string;
  isOffline: boolean;
}) {
  const [streams, setStreams] = useState<FeedStream[]>([]);
  const [loading, setLoading] = useState(true);
  const [notAvailable, setNotAvailable] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [adding, setAdding] = useState(false);

  const fetchStreams = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/feed/streams`);
      if (res.status === 404) {
        setNotAvailable(true);
        return;
      }
      if (res.ok) {
        const data = await res.json();
        setStreams(Array.isArray(data) ? data : data.streams || []);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchStreams();
  }, [fetchStreams]);

  async function handleToggle(streamId: number, active: boolean) {
    try {
      const res = await fetch(
        `/api/agents/${agentId}/feed/streams/${streamId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active: !active }),
        }
      );
      if (res.status === 404) {
        setNotAvailable(true);
        return;
      }
      if (res.ok || res.status === 204) {
        await fetchStreams();
      }
    } catch {
      // silent
    }
  }

  async function handleDelete(streamId: number) {
    try {
      const res = await fetch(
        `/api/agents/${agentId}/feed/streams/${streamId}`,
        { method: "DELETE" }
      );
      if (res.ok || res.status === 204) {
        await fetchStreams();
      }
    } catch {
      // silent
    }
  }

  async function handleAdd() {
    if (!newUrl.trim() || adding) return;
    setAdding(true);
    try {
      const res = await fetch(`/api/agents/${agentId}/feed/streams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: newUrl.trim(),
          label: newLabel.trim() || undefined,
        }),
      });
      if (res.status === 404) {
        setNotAvailable(true);
        return;
      }
      if (res.ok) {
        setNewUrl("");
        setNewLabel("");
        setShowAdd(false);
        await fetchStreams();
      }
    } catch {
      // silent
    } finally {
      setAdding(false);
    }
  }

  if (notAvailable) {
    return (
      <div className="p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg">
        <h3 className="text-xs font-medium text-[#9a8c7a] mb-1">
          RSS Streams
        </h3>
        <p className="text-xs text-[#525252]">
          Stream management not available yet
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-[#9a8c7a] uppercase tracking-wider">
          RSS Streams
        </h3>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="text-xs text-[#525252] hover:text-[#d4a574] transition-colors"
          disabled={isOffline}
        >
          {showAdd ? "Cancel" : "+ Add"}
        </button>
      </div>

      {showAdd && (
        <div className="space-y-2 p-3 bg-[#12121a] border border-[#d4a574]/20 rounded-lg">
          <input
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            placeholder="RSS feed URL"
            className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded text-xs focus:outline-none focus:border-[#d4a574] transition-colors"
          />
          <input
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder="Label (optional)"
            className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded text-xs focus:outline-none focus:border-[#d4a574] transition-colors"
          />
          <button
            onClick={handleAdd}
            disabled={!newUrl.trim() || adding}
            className="w-full py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded text-xs font-medium disabled:opacity-50 transition-colors"
          >
            {adding ? "Adding..." : "Add stream"}
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-xs text-[#525252]">Loading streams...</div>
      ) : streams.length === 0 ? (
        <p className="text-xs text-[#525252] italic">No RSS streams yet</p>
      ) : (
        <div className="space-y-2">
          {streams.map((stream) => (
            <div
              key={stream.id}
              className="p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg group"
            >
              <div className="flex items-center justify-between">
                <div className="flex-1 min-w-0 mr-2">
                  <span className="text-xs text-[#d4d4d4] block truncate">
                    {stream.label || stream.url}
                  </span>
                  <span className="text-[10px] text-[#525252]">
                    {stream.items_fetched} items
                  </span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => handleToggle(stream.id, stream.active)}
                    disabled={isOffline}
                    className={`text-[10px] px-2 py-0.5 rounded-full transition-colors ${
                      stream.active
                        ? "bg-emerald-500/10 text-emerald-500"
                        : "bg-[#1e1e1a] text-[#525252]"
                    }`}
                  >
                    {stream.active ? "Active" : "Paused"}
                  </button>
                  <button
                    onClick={() => handleDelete(stream.id)}
                    disabled={isOffline}
                    className="text-xs text-[#525252] hover:text-[#ef4444] opacity-0 group-hover:opacity-100 transition-all"
                  >
                    ×
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
