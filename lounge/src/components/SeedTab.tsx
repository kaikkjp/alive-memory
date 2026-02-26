"use client";

import { useState, useEffect, useCallback } from "react";
import BackstoryCard from "./BackstoryCard";
import MemoryTimeline from "./MemoryTimeline";

interface Memory {
  source_id: string;
  source_type: string;
  text_content: string;
  ts_iso: string;
  origin: string;
}

interface SeedTabProps {
  agentId: string;
}

export default function SeedTab({ agentId }: SeedTabProps) {
  const [section, setSection] = useState<"seeds" | "memories">("seeds");
  const [backstory, setBackstory] = useState<Memory[]>([]);
  const [organic, setOrganic] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newText, setNewText] = useState("");
  const [adding, setAdding] = useState(false);

  const fetchMemories = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/memories`);
      if (res.ok) {
        const data = await res.json();
        setBackstory(data.backstory || []);
        setOrganic(data.organic || []);
      }
    } catch {
      // silent
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
      // silent
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(sourceId: string) {
    try {
      const res = await fetch(
        `/api/agents/${agentId}/memories/${encodeURIComponent(sourceId)}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        await fetchMemories();
      }
    } catch {
      // silent
    }
  }

  return (
    <div className="space-y-3">
      {/* Section toggle */}
      <div className="flex gap-1">
        <button
          onClick={() => setSection("seeds")}
          className={`px-3 py-1.5 rounded-md text-xs transition-colors ${
            section === "seeds"
              ? "bg-[#262626] text-white"
              : "text-[#737373] hover:text-white"
          }`}
        >
          Your Seeds ({backstory.length})
        </button>
        <button
          onClick={() => setSection("memories")}
          className={`px-3 py-1.5 rounded-md text-xs transition-colors ${
            section === "memories"
              ? "bg-[#262626] text-white"
              : "text-[#737373] hover:text-white"
          }`}
        >
          Her Memories ({organic.length})
        </button>
      </div>

      {loading ? (
        <div className="text-xs text-[#525252]">Loading memories...</div>
      ) : section === "seeds" ? (
        <div className="space-y-2">
          {backstory.length === 0 && !showAddForm && (
            <p className="text-xs text-[#525252] italic">
              No backstory yet. Plant memories to shape who she was before.
            </p>
          )}

          {backstory.map((mem) => (
            <BackstoryCard
              key={mem.source_id}
              sourceId={mem.source_id}
              text={mem.text_content}
              date={mem.ts_iso}
              onDelete={handleDelete}
            />
          ))}

          {showAddForm ? (
            <div className="p-3 bg-[#12121a] border border-[#d4a574]/30 rounded-lg space-y-2">
              <input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="Title (optional)"
                className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded text-xs focus:outline-none focus:border-[#d4a574] transition-colors"
              />
              <textarea
                value={newText}
                onChange={(e) => setNewText(e.target.value)}
                placeholder="A moment, a feeling, a place..."
                rows={3}
                className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded text-xs focus:outline-none focus:border-[#d4a574] transition-colors resize-y"
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
                  {adding ? "Planting..." : "Plant seed"}
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowAddForm(true)}
              className="w-full py-2 border border-dashed border-[#262620] text-[#737373] hover:text-[#d4a574] hover:border-[#d4a574]/30 rounded-lg text-xs transition-colors"
            >
              + Plant a backstory seed
            </button>
          )}
        </div>
      ) : (
        <MemoryTimeline memories={organic} />
      )}
    </div>
  );
}
