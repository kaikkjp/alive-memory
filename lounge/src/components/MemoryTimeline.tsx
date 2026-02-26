"use client";

import { useState, useMemo } from "react";

interface MemoryEntry {
  source_id: string;
  source_type: string;
  text_content: string;
  ts_iso: string;
}

interface MemoryTimelineProps {
  memories: MemoryEntry[];
}

const TYPE_LABELS: Record<string, string> = {
  journal: "Journal",
  dream: "Dream",
  visitor_conversation: "Visitor",
  consolidation: "Reflection",
};

const TYPE_COLORS: Record<string, string> = {
  journal: "text-[#d4a574]",
  dream: "text-[#b0a0c0]",
  visitor_conversation: "text-[#8b9dc3]",
  consolidation: "text-[#9a8c7a]",
};

export default function MemoryTimeline({ memories }: MemoryTimelineProps) {
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!search.trim()) return memories;
    const q = search.toLowerCase();
    return memories.filter(
      (m) =>
        m.text_content.toLowerCase().includes(q) ||
        (m.source_type ?? "").toLowerCase().includes(q)
    );
  }, [memories, search]);

  function formatDate(ts: string): string {
    try {
      const d = new Date(ts);
      return d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return ts;
    }
  }

  return (
    <div className="space-y-3">
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search memories..."
        className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded-lg text-xs focus:outline-none focus:border-[#d4a574] transition-colors"
      />

      {filtered.length === 0 ? (
        <p className="text-xs text-[#525252] italic">
          {search
            ? "No memories match your search."
            : "No organic memories yet. These form through conversations and experiences."}
        </p>
      ) : (
        <div className="space-y-1.5">
          {filtered.map((mem) => {
            const isExpanded = expandedId === mem.source_id;
            const preview =
              mem.text_content.length > 100
                ? mem.text_content.slice(0, 100) + "..."
                : mem.text_content;

            return (
              <div
                key={mem.source_id}
                onClick={() =>
                  setExpandedId(isExpanded ? null : mem.source_id)
                }
                className="p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg cursor-pointer hover:border-[#262620] transition-colors"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-[10px] ${TYPE_COLORS[mem.source_type] || "text-[#525252]"}`}
                  >
                    {TYPE_LABELS[mem.source_type] || mem.source_type}
                  </span>
                  <span className="text-[10px] text-[#525252]">
                    {formatDate(mem.ts_iso)}
                  </span>
                </div>
                <p className="text-xs text-[#a3a3a3] leading-relaxed">
                  {isExpanded ? mem.text_content : preview}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
