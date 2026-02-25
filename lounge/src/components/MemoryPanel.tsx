"use client";

import { useState, useEffect, useCallback } from "react";

interface Memory {
  source_id: string;
  source_type: string;
  text_content: string;
  ts_iso: string;
  origin: string;
}

interface MemoryPanelProps {
  agentId: string;
  onClose: () => void;
}

export default function MemoryPanel({ agentId, onClose }: MemoryPanelProps) {
  const [tab, setTab] = useState<"backstory" | "organic">("backstory");
  const [backstory, setBackstory] = useState<Memory[]>([]);
  const [organic, setOrganic] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [newTitle, setNewTitle] = useState("");
  const [newText, setNewText] = useState("");
  const [adding, setAdding] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const fetchMemories = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/memories`);
      if (res.ok) {
        const data = await res.json();
        setBackstory(data.backstory || []);
        setOrganic(data.organic || []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchMemories();
  }, [fetchMemories]);

  async function handleAdd() {
    if (!newText.trim()) return;
    setAdding(true);
    try {
      const res = await fetch(`/api/agents/${agentId}/memories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: newText.trim(),
          title: newTitle.trim() || undefined,
        }),
      });
      if (res.ok) {
        setNewTitle("");
        setNewText("");
        setShowAddForm(false);
        await fetchMemories();
      }
    } catch {
      // ignore
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(sourceId: string) {
    setDeleteConfirm(null);
    try {
      const res = await fetch(`/api/agents/${agentId}/memories/${encodeURIComponent(sourceId)}`, {
        method: "DELETE",
      });
      if (res.ok) {
        await fetchMemories();
      }
    } catch {
      // ignore
    }
  }

  function formatDate(ts: string): string {
    try {
      return new Date(ts).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return ts;
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-full max-w-lg bg-[#0f0f14] border-l border-[#1e1e1a] flex flex-col h-full animate-slide-in-right">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#1e1e1a]">
          <h2 className="text-base font-semibold">Memories</h2>
          <button
            onClick={onClose}
            className="text-[#737373] hover:text-white text-lg transition-colors"
          >
            &times;
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-5 pt-3 pb-2">
          <button
            onClick={() => setTab("backstory")}
            className={`px-3 py-1.5 rounded-md text-xs transition-colors ${
              tab === "backstory"
                ? "bg-[#262626] text-white"
                : "text-[#737373] hover:text-white"
            }`}
          >
            Backstory ({backstory.length})
          </button>
          <button
            onClick={() => setTab("organic")}
            className={`px-3 py-1.5 rounded-md text-xs transition-colors ${
              tab === "organic"
                ? "bg-[#262626] text-white"
                : "text-[#737373] hover:text-white"
            }`}
          >
            Her memories ({organic.length})
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-3">
          {loading ? (
            <p className="text-sm text-[#737373]">Loading memories...</p>
          ) : tab === "backstory" ? (
            <div className="space-y-3">
              {backstory.length === 0 && !showAddForm && (
                <p className="text-sm text-[#525252] italic">
                  No backstory yet. Add memories to shape who she was before.
                </p>
              )}

              {backstory.map((mem) => (
                <div
                  key={mem.source_id}
                  className="p-3 bg-[#12121a] border border-[#262620] rounded-lg group"
                >
                  <div className="flex justify-between items-start mb-1.5">
                    <span className="text-xs text-[#737373]">
                      {formatDate(mem.ts_iso)}
                    </span>
                    <button
                      onClick={() => setDeleteConfirm(mem.source_id)}
                      className="text-xs text-[#525252] hover:text-[#ef4444] opacity-0 group-hover:opacity-100 transition-all"
                    >
                      Remove
                    </button>
                  </div>
                  <p className="text-sm text-[#d4d4d4] leading-relaxed">
                    {mem.text_content}
                  </p>
                </div>
              ))}

              {/* Add form */}
              {showAddForm ? (
                <div className="p-3 bg-[#12121a] border border-[#d4a574]/30 rounded-lg space-y-3">
                  <input
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="Title (optional)"
                    className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded text-sm focus:outline-none focus:border-[#d4a574] transition-colors"
                  />
                  <textarea
                    value={newText}
                    onChange={(e) => setNewText(e.target.value)}
                    placeholder="What happened? A moment, a feeling, a place..."
                    rows={4}
                    className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded text-sm focus:outline-none focus:border-[#d4a574] transition-colors resize-y"
                  />
                  <div className="flex gap-2 justify-end">
                    <button
                      onClick={() => {
                        setShowAddForm(false);
                        setNewTitle("");
                        setNewText("");
                      }}
                      className="px-3 py-1.5 text-xs text-[#737373] hover:text-white transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleAdd}
                      disabled={!newText.trim() || adding}
                      className="px-3 py-1.5 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded text-xs font-medium disabled:opacity-50 transition-colors"
                    >
                      {adding ? "Adding..." : "Add memory"}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setShowAddForm(true)}
                  className="w-full py-2.5 border border-dashed border-[#262620] text-[#737373] hover:text-[#d4a574] hover:border-[#d4a574]/30 rounded-lg text-xs transition-colors"
                >
                  + Add backstory memory
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {organic.length === 0 && (
                <p className="text-sm text-[#525252] italic">
                  No organic memories yet. These form naturally through
                  conversations and experiences.
                </p>
              )}
              {organic.map((mem) => (
                <div
                  key={mem.source_id}
                  className="p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
                >
                  <div className="flex justify-between items-center mb-1.5">
                    <span className="text-xs text-[#525252]">
                      {mem.source_type}
                    </span>
                    <span className="text-xs text-[#525252]">
                      {formatDate(mem.ts_iso)}
                    </span>
                  </div>
                  <p className="text-sm text-[#a3a3a3] leading-relaxed">
                    {mem.text_content}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[60]">
          <div className="bg-[#1a1a1a] border border-[#262620] rounded-xl p-5 max-w-xs mx-4">
            <h3 className="text-sm font-semibold mb-2">Remove memory?</h3>
            <p className="text-xs text-[#a3a3a3] mb-4">
              This backstory memory will be permanently removed.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-3 py-1.5 text-xs text-[#737373] hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                className="px-3 py-1.5 bg-[#ef4444]/80 hover:bg-[#ef4444] text-white rounded text-xs transition-colors"
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        @keyframes slide-in-right {
          from {
            transform: translateX(100%);
          }
          to {
            transform: translateX(0);
          }
        }
        .animate-slide-in-right {
          animation: slide-in-right 0.2s ease-out;
        }
      `}</style>
    </div>
  );
}
