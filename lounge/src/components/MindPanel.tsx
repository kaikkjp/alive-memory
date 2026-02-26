"use client";

import { useRef, useEffect } from "react";
import type { InnerVoiceEntry } from "@/lib/types";

interface MindPanelProps {
  entries: InnerVoiceEntry[];
  status: "connected" | "reconnecting" | "offline" | "error";
}

function formatRelativeTime(timestamp: string): string {
  try {
    const diff = Date.now() - new Date(timestamp).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  } catch {
    return "";
  }
}

export default function MindPanel({ entries, status }: MindPanelProps) {
  const prevCountRef = useRef(entries.length);
  const containerRef = useRef<HTMLDivElement>(null);

  // Track new entries for fade-in
  const isNewEntry = entries.length > prevCountRef.current;
  useEffect(() => {
    prevCountRef.current = entries.length;
  }, [entries.length]);

  if (status === "offline" || status === "error") {
    return (
      <div className="h-full flex items-center justify-center px-4">
        <p className="text-xs text-[#525252] italic">
          {status === "offline" ? "She's offline" : "Connection lost"}
        </p>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="h-full flex items-center justify-center px-4">
        <p className="text-xs text-[#525252] italic">
          Her thoughts will appear here...
        </p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="h-full overflow-y-auto px-3 py-2 space-y-2">
      {entries.map((entry, i) => (
        <div
          key={`${entry.timestamp}-${i}`}
          className={`${i === 0 && isNewEntry ? "animate-fade-in" : ""}`}
        >
          <div className="flex items-baseline gap-2 mb-0.5">
            <span className="text-[10px] text-[#525252] shrink-0">
              {formatRelativeTime(entry.timestamp)}
            </span>
            {entry.cycle_type && (
              <span className="text-[10px] text-[#3a3a3a]">
                {entry.cycle_type}
              </span>
            )}
          </div>
          <p className="text-xs text-[#a3a3a3] italic leading-relaxed">
            &ldquo;{entry.text}&rdquo;
          </p>
        </div>
      ))}
    </div>
  );
}
